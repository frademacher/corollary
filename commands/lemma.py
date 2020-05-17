#!/usr/bin/env python3

"""corollary command implementations for LEMMA builds."""

from abc import abstractmethod
from corollary import Argument, Command, CommandScope, Variable
from fileinput import FileInput
from jproperties import Properties
from lxml import etree
from pathlib import Path

import os
import re
import subprocess
import sys

class AskForVersion(Command):
    """ask_for_version: Ask user for LEMMA version."""

    def name(self):
        """Command name."""

        return 'ask_for_version'

    def provided_variables(self):
        """Provided variables."""

        return [Variable('version')]

    def execute(self, values):
        """Execution logic.

        Ask the user to enter the version number to be used for the LEMMA build.
        """

        version = input('Please specify a version number: ')
        if not version:
            raise ValueError('No version number given.')
        return {'version': version}

class ReadVersionFrom(Command):
    """read_version_from: Read LEMMA version from properties file."""

    def name(self):
        """Command name."""

        return 'read_version_from'

    def arguments(self):
        """Expected arguments."""

        return [Argument('filepath')]

    def provided_variables(self):
        """Provided variables."""

        return [Variable('version')]

    def execute(self, values):
        """Execution logic.

        Read LEMMA version from a Java properties file that specifies at least
        a "major", "minor", and "patch" entry.
        """

        filepath = values['filepath']
        if not os.path.isabs(filepath):
            filepath = os.path.join(self.get_target_directory(), filepath)

        p = Properties()
        with open(filepath, 'rb') as fd:
            p.load(fd)
        major = self._get_key(p, 'major')
        minor = self._get_key(p, 'minor')
        patch = self._get_key(p, 'patch')
        extra = self._get_key(p, 'extra')

        if not major or not minor or not patch:
            raise ValueError('Properties file "%s" must specify keys "major" \
                "minor" and "patch".')

        version = '%s.%s.%s' % (major, minor, patch)
        if extra:
            version += '.' + extra
        return {'version': version}

    def _get_key(self, p, k):
        """Return None instead of a KeyError for non-existent properties."""

        try:
            value, _ = p[k]
            return value
        except KeyError:
            return None

class AskForSnapshot(Command):
    """ask_for_snapshot: Ask the user if this a snapshot build."""

    SNAPSHOT_IDENTIFIER = '-SNAPSHOT'

    def name(self):
        """Command name."""

        return 'ask_for_snapshot'

    def required_variable_names(self):
        """Required variables."""

        return ['version']

    def provided_variables(self):
        """Provided variables."""

        return [Variable('version')]

    def execute(self, values):
        """Execution logic.

        Ask the user if the version number for the LEMMA build is a snapshot.
        """
        try:
            self.get_scope_variable_value('snapshot')
            return
        except KeyError:
            pass

        version = self.get_scope_variable_value('version')
        isSnapshot = input('Is this a snapshot release? [y/n] ')
        if isSnapshot.lower() == 'y':
            return {'version': version + self.SNAPSHOT_IDENTIFIER}
        else:
            return {'version': version}

class AskForContinuation(Command):
    """ask_for_continuation: Ask the user if she wants to continue.

    The command takes the name of a variable, whose value is displayed when the
    user is asked if she wants to continue.
    """

    def name(self):
        """Command name."""

        return 'ask_for_continuation'

    def arguments(self):
        """Expected arguments."""

        return [Argument('variable')]

    def execute(self, values):
        """Execution logic.

        Ask the user if she wants to continue by also printing the passed
        variable's value.
        """

        variable = values['variable']
        try:
            value = self.get_scope_variable_value(variable)
        except KeyError:
            print('Variable "%s" not found in scope. Exiting.' % variable)
            sys.exit(4)

        cont = input('Continue? (%s = %s) [y/n] ' % (variable, str(value)))
        if cont and cont.lower() != 'y':
            print('Exiting.')
            sys.exit(0)

class AbstractMavenCommand(Command):
    """Abstract Command baseclass for commands that execute mvn."""

    @abstractmethod
    def get_basic_command(self):
        """Get the basic Maven command to be executed."""

        pass

    def maximum_scope(self):
        """Determine maximum scope for the command's application."""

        return CommandScope.MODULE

    def required_variable_names(self):
        """Required variables."""

        return ['version']

    def execute(self, values):
        """Execution logic.

        Execute the basic Maven command in the directory represented by the
        current module in the given target directory. The current version
        number is appended to the basic Maven command.
        """

        # Determine module directory within target directory and logfile path
        # within target directory
        module = self.get_scope_variable_value('module')
        moduleDir = os.path.join(self.get_target_directory(), module)
        if not os.path.isdir(moduleDir):
            print('Module directory "%s" does not exist. Exiting.' % moduleDir)
        version = self.get_scope_variable_value('version')
        logfile = os.path.join(self.get_target_directory(), 'mvn.log')

        # Execute the basic Maven command and store log in a logfile (-l mvn
        # command-line argument)
        mvnCommand = 'mvn -l %s %s%s' % (logfile, self.get_basic_command(),
            version)
        print('%s: %s' % (module, mvnCommand), end='', flush=True)
        result = subprocess.run(mvnCommand.split(), cwd=moduleDir)
        if result.returncode == 0:
            print(' [DONE]')
        else:
            print('\n\tAn error occurred! mvn output can be found in file ' \
                '"%s". Exiting.' % logfile)
            sys.exit(4)

class MavenTychoSetVersion(AbstractMavenCommand):
    """mvn_tycho_set_version: Run set-version task of Tycho's version plugin.

    The task can be used to set the version XML element in a POM file.
    """

    def name(self):
        """Command name."""

        return 'mvn_tycho_set_version'

    def get_basic_command(self):
        """Basic Maven command."""

        return 'org.eclipse.tycho:tycho-versions-plugin:' \
            'set-version -DnewVersion='

class MavenUpdateParentVersion(AbstractMavenCommand):
    """mvn_update_parent_version: Run update-parent of Maven's version plugin.

    The task can be used to set the version of a referenced parent POM file.
    """

    def name(self):
        """Command name."""

        return 'mvn_update_parent_version'

    def get_basic_command(self):
        """Basic Maven command."""

        return 'versions:update-parent -DgenerateBackupPoms=false ' \
            '-DallowSnapshots=true -DparentVersion='

class MavenUpdateParentVersionRaw(Command):
    """mvn_update_parent_version_raw: Raw update of Maven parents.

    This is a version of the mvn_update_parent_version command (see above) that
    directly manipulates the version XML element in the parent element of the
    POM file within the current module. This is helpful, when
    mvn_update_parent_version and the update-parent of Maven's version plugin
    refuse to update the parent version, e.g., because a newer than the given
    version exists in the local Maven repository.

    With this command, the version of the referenced parent POM can be set to an
    arbitrary value due to direct manipulation of the XML file.
    """

    _POM_NAMESPACE = 'http://maven.apache.org/POM/4.0.0'

    def name(self):
        """Command name."""

        return 'mvn_update_parent_version_raw'

    def maximum_scope(self):
        """Determine maximum scope for the command's application."""

        return CommandScope.MODULE

    def required_variable_names(self):
        """Required variables."""

        return ['version']

    def execute(self, values):
        """Execution logic.


        Replace referenced parent POM's version with version value for the LEMMA
        build.
        """

        # Determine module directory within current target directory
        module = self.get_scope_variable_value('module')
        moduleDir = os.path.join(self.get_target_directory(), module)
        if not os.path.isdir(moduleDir):
            print('Module directory "%s" does not exist. Exiting.' % moduleDir)

        # Parse the module's POM
        pomFile = os.path.join(moduleDir, 'pom.xml')
        version = self.get_scope_variable_value('version')
        try:
            pomXml = etree.parse(pomFile)
        except IOError as err:
            print('Could not open POM file "%s" (error was: %s). Exiting.' % \
                (pomFile, str(err)))
            sys.exit(4)

        # Retrieve the referenced parent POM's version from the parsed POM
        try:
            pomParentVersion = pomXml.findall(
                '/{%(ns)s}parent/{%(ns)s}version' % \
                {'ns': self._POM_NAMESPACE}
            )[0]
        except IndexError:
            print('POM file "%s" does not specify a parent version. ' \
                'Exiting.' % pomFile)
            sys.exit(4)

        # Change the referenced parent POM's version to the version value for
        # the LEMMA build and write back the changes to the module's POM
        pomParentVersion.text = version
        pomXml.write(pomFile, pretty_print=True)

class OsgiUpdateBundleVersion(Command):
    """osgi_update_bundle_version: Update an OSGi bundle's Bundle-Version."""

    def name(self):
        """Command name."""

        return 'osgi_update_bundle_version'

    def maximum_scope(self):
        """Determine maximum scope for the command's application."""

        return CommandScope.MODULE

    def required_variable_names(self):
        """Required variables."""

        return ['version']

    def execute(self, values):
        """Execution logic.

        Set the Bundle-Version in the MANIFEST.MF file in the current module's
        directory to the version number for the LEMMA build.
        """

        # Determine module directory within current target directory
        module = self.get_scope_variable_value('module')
        moduleDir = os.path.join(self.get_target_directory(), module)
        if not os.path.isdir(moduleDir):
            print('Module directory "%s" does not exist. Exiting.' % moduleDir)

        # Manipulate the MANIFEST.MF OSGi bundle specification in the module
        # directory's META-INF folder
        manifestFile = os.path.join(moduleDir, 'META-INF', 'MANIFEST.MF')
        try:
            with FileInput(files=(manifestFile), inplace=True) as fd:
                for line in fd:
                    if line.strip().startswith('Bundle-Version:'):
                        print('Bundle-Version: ' + self._get_osgi_version())
                    else:
                        print(line, end='')
        except IOError as err:
            print('Could not open OSGi manifest file "%s" (error was: %s).' \
                'Exiting.' % (manifestFile, str(err)))
            sys.exit(4)

    def _get_osgi_version(self):
        """Adapt the LEMMA build version to be OSGi-compliant.

        More specifically, replace "-SNAPSHOT" with ".qualifier".
        """

        version = self.get_scope_variable_value('version')
        if version.endswith(AskForSnapshot.SNAPSHOT_IDENTIFIER):
            osgiVersion = version[:-len(AskForSnapshot.SNAPSHOT_IDENTIFIER)]
            osgiVersion += '.qualifier'
            return osgiVersion
        else:
            return version

class UpdatePropertiesFile(Command):
    """update_properties_file: Update a Java properties file.

    The command takes the path of the properties file relative to the current
    module's path. Moreover, it expects the name of the property to be updated
    within the given properties file, as well as the name of the variable, whose
    current value shall be assigned to the property.
    """

    def name(self):
        """Command name."""

        return 'update_properties_file'

    def maximum_scope(self):
        """Determine maximum scope for the command's application."""

        return CommandScope.MODULE

    def arguments(self):
        """Expected arguments."""

        return [Argument('filepath'), Argument('propertyName'),
            Argument('variable')]

    def execute(self, values):
        """Execution logic.

        Replace property value with variable value.
        """

        # Retrieve current variable value
        variable = values['variable']
        try:
            value = self.get_scope_variable_value(variable)
        except KeyError:
            print('Variable "%s" not found in scope. Exiting.' % variable)
            sys.exit(4)

        # Determine module directory within target directory
        module = self.get_scope_variable_value('module')
        moduleDir = os.path.join(self.get_target_directory(), module)
        if not os.path.isdir(moduleDir):
            print('Module directory "%s" does not exist. Exiting.' % moduleDir)

        # Raw-read and manipulation of the Java properties file to preserve comments and empty
        # lines
        propertiesFile = os.path.join(moduleDir, values['filepath'])
        propertyRegex = re.compile('%s\s*=\s*(?P<value>.*)' % \
            values['propertyName'])
        try:
            with FileInput(files=(propertiesFile), inplace=True) as fd:
                for rawLine in fd:
                    line = rawLine.strip()
                    propertyMatch = propertyRegex.match(line)
                    if propertyMatch:
                        propertyValue = propertyMatch.group('value')
                        propertyValueBegin = line[:-len(propertyValue)]
                        print(propertyValueBegin + value)
                    else:
                        print(line)
        except IOError as err:
            print('Could not open properties file "%s" (error was: %s).' \
                'Exiting.' % (propertiesFile, str(err)))
            sys.exit(4)

class DeleteFile(Command):
    """delete_file: Delete a file within the target directory."""

    def name(self):
        """Command name."""

        return 'delete_file'

    def arguments(self):
        """Expected arguments."""

        return [Argument('filepath')]

    def execute(self, values):
        """Execution logic."""

        filepath = values['filepath']
        targetDir = self.get_target_directory()
        if not os.path.isabs(filepath):
            try:
                module = self.get_scope_variable_value('module')
            except KeyError:
                module = ''
            filepath = os.path.join(targetDir, module, filepath)

        if not Path(targetDir) in Path(filepath).parents:
            print('File "%s" is not in target directory "%s" and thus cannot ' \
                'be deleted. Exiting.' % (filepath, targetDir))
            sys.exit(4)

        try:
            os.remove(filepath)
        except IOError:
            pass