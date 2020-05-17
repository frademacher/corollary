#!/usr/bin/env python3

from abc import ABC, abstractmethod
from enum import Enum
from yaml.loader import SafeLoader

import argparse
import copy
import importlib
import inspect
import logging
import os
import re
import shlex
import sys
import yaml

_NAME = 'corollary'
_VERSION = '0.5'

class Commandline:
    """Parses and clusters command-line arguments."""

    def __init__(self):
        """Constructor."""

        self._argument_parser = argparse.ArgumentParser(
            description='Corollary - Your Simple Command Executor')
        self._argument_parser.add_argument('-c', '--command_directory',
            dest='commandDirectory', help='Directory of available commands',
            required=True)
        self._argument_parser.add_argument('-f', '--formula',
            dest='formula', required=True, help='The formula to be executed')
        self._argument_parser.add_argument('-t', '--target_directory',
            dest='targetDirectory', required=True, help='The directory in ' \
                'whose context the formula shall be executed')

    def parse_arguments(self):
        """Parse the command-line arguments of the script."""

        self._parsed_arguments = self._argument_parser.parse_args()

    @property
    def command_directory(self):
        """Passed command directory."""

        return self._parsed_arguments.commandDirectory

    @property
    def formula(self):
        """Passed formula file."""

        return self._parsed_arguments.formula

    @property
    def target_directory(self):
        """Passed target directory."""

        return self._parsed_arguments.targetDirectory

class Commands:
    """Holds information about commands found in the command directory."""

    def __init__(self, commandDirectory):
        """Constructor."""

        self._load_builtin_commands()
        self._load_commands_from_directory(commandDirectory)

    def _load_builtin_commands(self):
        """Load built-in commands.

        Built-in commands are commands that inherit from the BuiltinCommand
        class.
        """

        thisModule = inspect.getmodule(self)
        self._builtin_commands = {}
        commands = self._load_commands(thisModule, '__main__', 'BuiltinCommand')
        for command in commands:
            self._builtin_commands[command.get_name()] = command

    def _load_commands_from_directory(self, directory):
        """Load commands from the specified directory."""

        self._commands = {}

        # Only those commands are loaded that are explicitly exported as
        # submodules via the Python package descriptor (file "__init__.py") and
        # the __all__ variable, e.g., __all__ = ['cmds']
        exportedModules = importlib.import_module(directory).__all__
        qualifiedSubmoduleNames = [directory + '.' + n for n in exportedModules]
        loadedSubmodules = [importlib.import_module(m, package=directory)
            for m in qualifiedSubmoduleNames]

        # Load commands from exported submodules
        for submodule in loadedSubmodules:
            sys.path.append(submodule.__file__)
            loadedCommands = self._load_commands(submodule)
            self._validate_and_register_external_commands(loadedCommands)

    def _load_commands(self, submodule, commandClassModule='corollary',
        commandClassName='Command'):
        """Load commands from the passed submodule.

        The commandClassModule and commandClassName determine the class, from
        which valid commands need to inherit. By default, this is the Command
        class contained in this module (see below).
        """

        classes = self._find_command_classes(submodule, commandClassModule,
            commandClassName)
        return [self._init_command(c, submodule.__file__) for c in classes]

    def _find_command_classes(self, submodule, superclassModule,
        superclassName):
        """Find all classes that represent commands.

        A class represents a command, if it directly or indirectly inherits from
        the given superclassName in the given superclassModule.
        """

        classes = [c for c in self._filter_abstract_classes(submodule)
            if self._has_superclass(superclassModule, superclassName, c)]
        return classes

    def _filter_abstract_classes(self, submodule):
        """Filter abstract classes in the given submodule."""

        return [c[1] for c in inspect.getmembers(submodule, inspect.isclass)
            if not inspect.isabstract(c[1])]

    def _has_superclass(self, superclassModule, superclassName, clazz):
        """Check if a class inherits directly or indirectly from another class.

        The class to check is represented by the clazz argument. The super
        class to check is represented by the superclassName argument and is
        expected to be contained in the given superclassModule.
        """

        superclassQualifiedName = superclassModule + '.' + superclassName
        mro = inspect.getmro(clazz)
        for m in mro:
            # We identify an inheritance relationship between two classes by
            # means of their qualified names. The qualified name consists of the
            # class's module and name, separated by a dot.
            mroQualifiedName = m.__module__ + '.' + m.__name__
            if mroQualifiedName == superclassQualifiedName:
                return True
        return False

    def _validate_and_register_external_commands(self, commands):
        """Validate and register "external", i.e., non-built-in, commands.

        External commands usually originate from the command directory passed to
        corollary.
        """

        for c in commands:
            # An external command must not exhibit the same name as a built-in
            # command
            if c.get_name() in self._builtin_commands:
                raise ValueError('Error while registering command class %s ' \
                    '(file "%s"): Command name "%s" is reserved for built-in' \
                    'comamnd' % (c.get_classname(), c.get_file(), c.get_name()))
            # Names of external commands must be unique
            elif c.get_name() in self._commands:
                raise ValueError('Error while registering command class %s ' \
                    '(file "%s"): Duplicate command name "%s"' %\
                    (c.get_classname(), c.get_file(), c.get_name()))

            # Register the command. That is, store the command under its name in
            # the command dictionary maintained by the Commands class.
            self._commands[c.get_name()] = c

    def _init_command(self, commandClass, file):
        """Initialize a command."""

        # Instantiate the command
        commandInstance = commandClass(file, commandClass)
        # Receive initialization values as specified by the command's
        # implementer, i.e., the non-abstract class that inherits from the
        # super class for commands
        commandInstance.init_from_implementer()
        return commandInstance

    def get_command(self, commandName):
        """Get command with the given name."""

        if self.is_builtin_command(commandName):
            return self._builtin_commands[commandName]
        else:
            return self._commands[commandName]

    def is_builtin_command(self, commandName):
        """Check if the class with the given name is a built-in command."""

        return commandName in self._builtin_commands

    def get_builtin_provided_variables(self):
        """Retrieve the set of the names of all provided command variables."""

        try:
            return self._provided_builtin_variables
        except AttributeError:
            self._provided_builtin_variables = set()
            for bc in self._builtin_commands.values():
                self._provided_builtin_variables.update(
                    [v.get_name() for v in bc.get_provided_variables()]
                )
            return self._provided_builtin_variables

class Command(ABC):
    """Abstract baseclass for commands."""

    def __init__(self, file, clazz):
        """Constructor."""

        self._file = file
        self._clazz = clazz

    def init_from_implementer(self):
        """Initialize a Command instance with values provided by implemters.

        An implementer of Command is a non-abstract class that represents a
        concrete command. This method invokes the implementations of template
        methods of the implementer, that provide initialization values for the
        command instance.

        The initialization of a concrete command with values from its
        implementers is handled separately from the constructor, to increase the
        performance of Command.new_instance(), which simply copies the values of
        an already initialized Command instance.
        """

        name = self._must_be_string(self.name(), 'command name')

        maximumScope = self._must_be_enum(self.maximum_scope(),
            'maximum command scope', CommandScope)

        arguments = self._must_be_list_of_types(self.arguments(), Argument,
            'command arguments')
        for arg in arguments:
            arg.init_internal(self._file, name)
            arg.validate()

        providedVars = self._must_be_list_of_types(self.provided_variables(),
            Variable, 'provided variables')
        for v in providedVars:
            v.init_internal(self._file, name)
            v.validate()

        requiresVarsNames = self._must_be_list_of_types(
            self.required_variable_names(),
            str,
            'required variable names'
        )

        self._init_from_values(name, maximumScope, arguments, providedVars,
            requiresVarsNames)

    def _init_from_values(self, name, maximumScope, arguments, providedVars,
        requiresVarsNames):
        """Reusable helper to initialize values of the Command."""

        self._classname = self._clazz.__name__
        self._name = name
        self._maximumScope = maximumScope
        self._arguments = arguments
        self._provided_variables = providedVars
        self._required_variable_names = requiresVarsNames

    def new_instance(self):
        """Create a new instance of a concrete Command implementation.

        To create the new instance, the values determining the state of the
        copy's source instance are copied. That is, the initialization methods
        of the implementer need not be invoked again.
        """

        newInstance = self._clazz(self._file, self._clazz)
        newInstance._init_from_values(self._name, self._maximumScope,
            self._arguments, self._provided_variables,
            self._required_variable_names)
        return newInstance

    @abstractmethod
    def name(self):
        """For implementers: Name of a concrete command."""

        pass

    def get_name(self):
        """Get a concrete command's name."""

        return self._name

    def get_file(self):
        """Get a concrete command's file."""

        return self._file

    def get_classname(self):
        """Get the name of a concrete Command implementation's class."""

        return self._classname

    @abstractmethod
    def execute(self, argumentValues):
        """For implementers: Execution logic of a concrete command."""

        pass

    def set_target_directory(self, targetDirectory):
        """Pass the given target directoy to a concrete command."""

        self._targetDirectory = targetDirectory

    def get_target_directory(self):
        """Get the target directory."""

        return self._targetDirectory

    def set_scope_variables(self, scopeVariables):
        """Pass the current execution scope's variables to a command."""

        self._scopeVariables = scopeVariables

    def get_scope_variable_value(self, variableName):
        """Get the value of the given variable within the current scope."""

        return self._scopeVariables[variableName]

    def maximum_scope(self):
        """For implementers: Determine maximum scope of the command."""

        return CommandScope.GLOBAL

    def get_maximum_scope(self):
        """Get the maximum scope of a command."""

        return self._maximumScope

    def arguments(self):
        """For implementers: Determine the arguments of the command."""

        return []

    def get_arguments(self):
        """Get a command's argument definitions."""

        return self._arguments

    def provided_variables(self):
        """For implementers: Determine the variables provided by the command."""

        return []

    def get_provided_variables(self):
        """Get a command provided variable's definitions."""

        return self._provided_variables

    def required_variable_names(self):
        """For implementers: Determine the variable required by the command."""

        return []

    def get_required_variable_names(self):
        """Get the names of the variables required by a command."""

        return self._required_variable_names

    def _must_be_string(self, v, valueName, mandatory=True):
        """Check if a value is of type str.

        Returns the value, if it is of type str. If the mandatory flag is set
        to True, the passed str must not be empty.
        """

        if not isinstance(v, str):
            raise ValueError('Error while initializing command class %s ' \
                '(file "%s"): Value for %s must be string' % (self._classname,
                self._file, valueName))
        elif mandatory and not v:
            self._ensure_mandatory(v, valueName)
        return v

    def _ensure_mandatory(self, v, valueName):
        """Check if the passed value v is not empty.

        Throws a ValueError, if v is empty.
        """

        if not v:
            raise ValueError('Error while initializing command class %s ' \
                '(file "%s"): Value for %s must not be empty' % \
                (self._classname, self._file, valueName))

    def _must_be_enum(self, v, valueName, enum, mandatory=True):
        """Check if a value is of type Enum.

        Returns the value, if it is of type Enum. If the mandatory flag is set
        to True, the passed Enum must not be empty.
        """

        if not isinstance(v, enum):
            raise ValueError('Error while initializing command class %s ' \
                '(file "%s"): Value for %s must be %s enum' % (self._classname,
                self._file, valueName, enum.__name__))
        elif mandatory and not v:
            self._ensure_mandatory(v, valueName)
        return v

    def _must_be_list_of_types(self, v, type, valueName):
        """Check if a value is a list of instances of a given type.

        Returns the value, if it is a list of the given type's instances.
        """

        if not isinstance(v, list):
            raise ValueError('Error while initializing command %s (class ' \
                '"%s", file "%s"): Value for %s must be list' % (self._name,
                self._classname, self._file, valueName))

        for value in v:
            if not isinstance(value, type):
                raise ValueError('Error while initializing command %s ' \
                    '(class "%s", file "%s"): List for %s must only contain ' \
                    'instances of type %s' % (self._name, self._classname,
                    self._file, valueName, type.__name__))

        return v

class CommandScope(Enum):
    """Possible command scopes."""

    GLOBAL = 512
    GROUP = 256
    MODULE = 128

    def __str__(self):
        """Convert literal to str representation."""

        return self.name.lower()

class BuiltinCommand(Command):
    """Super class for built-in commands."""

    pass

class _GroupCommand(BuiltinCommand):
    """Built-in group command."""

    NAME = 'group'

    def name(self):
        """Determine the command's name."""

        return self.NAME

    def arguments(self):
        """Determine the command's arguments."""

        return [Argument('groupName')]

    def provided_variables(self):
        """Determine the variables provided by the command."""

        return [Variable('group')]

    def execute(self, values):
        """Execution logic of the command."""

        return {'group': values['groupName']}

class Argument:
    """Command argument."""

    def __init__(self, name):
        """Constructor."""

        self._name = name

    def get_name(self):
        """Retrieve the argument's name."""

        return self._name

    def init_internal(self, commandFile, commandName):
        """Initialize an argument. To be used by corollary only."""

        self.commandFile = commandFile
        self.commandName = commandName

    def validate(self):
        """Validate the argument's initialization."""

        self._validate_is_string(self._name, 'argument name')

    def _validate_is_string(self, v, valueName, mandatory=True):
        """Check if a value is of type str.

        If the mandatory flag is set to True, the passed str must not be empty.
        """

        if not isinstance(v, str):
            raise ValueError('Error while initializing argument of command ' \
                '%s (file "%s"): Value for %s must be string' % \
                (self.commandName, self.commandFile, valueName))
        elif mandatory and not v:
            raise ValueError('Error while initializing argument of command ' \
                '%s (file "%s"): Value for %s must not be empty' % \
                (self.commandName, self.commandFile, valueName))

class Variable:
    """Command variable."""

    def __init__(self, name):
        """Constructor."""

        self._name = name

    def get_name(self):
        """Get the variable's name."""

        return self._name

    def init_internal(self, commandFile, commandName):
        """Initialize a variable. To be used by corollary only."""

        self.commandFile = commandFile
        self.commandName = commandName

    def validate(self):
        """Validate the variable's initialization."""

        self._validate_is_string(self._name, 'argument name')

    def _validate_is_string(self, v, valueName, mandatory=True):
        """Check if a value is of type str.

        If the mandatory flag is set to True, the passed str must not be empty.
        """

        if not isinstance(v, str):
            raise ValueError('Error while initializing argument of command ' \
                '%s (file "%s"): Value for %s must be string' % \
                (self.commandName, self.commandFile, valueName))
        elif mandatory and not v:
            raise ValueError('Error while initializing argument of command ' \
                '%s (file "%s"): Value for %s must not be empty' % \
                (self.commandName, self.commandFile, valueName))

class _ModuleCommand(BuiltinCommand):
    """Built-in module command."""

    NAME = 'module'

    def name(self):
        """Determine the command's name."""

        return self.NAME

    def arguments(self):
        """Determine the command's arguments."""

        return [Argument('moduleName')]

    def provided_variables(self):
        """Determine the variables provided by the command."""

        return [Variable('module')]

    def execute(self, values):
        """Execution logic of the command."""

        return {'module': values['moduleName']}

class Formula:
    """A corollary formula."""

    def __init__(self, formulaFile, commands):
        """Constructor."""

        self._formulaFile = formulaFile
        self._commands = commands

        with open(formulaFile, 'r') as fd:
            self._unpackedEntries = \
                self._unpack_yaml_entries(yaml.load(fd, Loader=YamlLineLoader))

    def get_file(self):
        """Get the formula's file."""

        return self._formulaFile

    def _unpack_yaml_entries(self, yamlEntries):
        """Unpack YAML entries.

        Unpacking means that nested YAML scalars are lifted from nested lists
        and dictionaries to the "top level", i.e., they are mapped their line
        numbers of the defining formula and their nesting elements are ignored.
        """

        unpackedEntries = {}
        entryListsTodo = [(yamlEntries, 0)]
        while entryListsTodo:
            currentEntryList, nestingLevel = entryListsTodo.pop()
            for e in currentEntryList:
                scalars, nestedLists = self._unpack_yaml_entry(e)
                for lineno, scalar in scalars:
                    unpackedEntries[lineno] = (scalar, nestingLevel)
                for l in nestedLists:
                    entryListsTodo.append((l, nestingLevel+1))

        # YAML does not guarantee entry ordering. Sort unpacked entries by line
        # numbers to circumvent that constraint.
        return dict(sorted(unpackedEntries.items()))

    def _unpack_yaml_entry(self, entry):
        """Unpack a YAML entry."""

        if isinstance(entry, tuple):
            return ([self._unpack_yaml_scalar(entry)], [])
        elif isinstance(entry, dict):
            scalars = [self._unpack_yaml_scalar(k) for k in entry.keys()]
            nestedLists = [l for l in entry.values()]
            return (scalars, nestedLists)
        else:
            raise ValueError('Unexpected YAML entry type: %s. Could not ' \
                'unpack.' % type(entry).__name__)

    def _unpack_yaml_scalar(self, scalar):
        """Unpack a YAML scalar."""

        if isinstance(scalar, tuple):
            yamlScalar = scalar[0]
            lineno = scalar[1]
            return (lineno, yamlScalar)
        else:
            raise Exception('YAML scalar must be tuple (was %s)' % \
                type(entry).__name__)

    def get_unpacked_entries(self):
        """Get unpacked YAML entries."""

        return self._unpackedEntries

class YamlLineLoader(SafeLoader):
    """Implementation of a YAML loader that preserves line numbers."""

    def construct_scalar(self, node):
        """Keep line number for each YAML scalar."""

        scalar = super(YamlLineLoader, self).construct_scalar(node)
        return (scalar, node.start_mark.line + 1)

class ExecutionPlan:
    """An execution plan derived from a formula."""

    _COMMAND_REGEX = re.compile('(?P<command>\S*)(?P<argumentValues>.*)?')

    _GROUP_ENTRY = 'GROUP ENTRY'
    _GROUP_EXIT = 'GROUP EXIT'
    _MODULE_ENTRY = 'MODULE ENTRY'
    _MODULE_EXIT = 'MODULE EXIT'

    def __init__(self, commands, formula, targetDirectory):
        """Constructor."""

        self._commands = commands
        self._formulaFile = formula.get_file()
        self._targetDirectory = targetDirectory
        self._executionPlan = self._parse(formula)
        self._validate_scoping()

    def _parse(self, formula):
        """Parse a formula."""

        yamlEntries = formula.get_unpacked_entries()
        executionPlan = {}

        # Iterate of the formula's unpacked YAML scalars and parse commands
        for self._currentLineno, entryInfo in yamlEntries.items():
            (yamlScalar, nestingLevel) = entryInfo
            # Parse a command, its argument values, and internal execution
            # instructions
            instrsBefore, command, argumentValues, instrsAfter = \
                self._parse_command(yamlScalar)

            # Add the command to the execution plan
            if not self._currentLineno in executionPlan:
                executionPlan[self._currentLineno] = \
                    ([], command, argumentValues, [])
            # The line number of the command may already be assigned in the
            # execution plan, because an after execution instruction was added
            # (cf. _insert_after_execution_instruction_into_plan()). In this
            # case, keep existing internal execution instructions.
            else:
                existingBefore, _, _, existingAfter = \
                    executionPlan[self._currentLineno]
                executionPlan[self._currentLineno] = \
                    (existingBefore, command, argumentValues, existingAfter)

            # Add before execution instructions of the command
            if instrsBefore:
                self._insert_before_execution_instruction_into_plan(
                    executionPlan,
                    instrsBefore
                )

            # Add after execution instructions of the command
            if instrsAfter:
                self._insert_after_execution_instruction_into_plan(
                    executionPlan,
                    nestingLevel,
                    yamlEntries,
                    instrsAfter
                )

        return sorted(executionPlan.items())

    def _parse_command(self, yamlScalar):
        """Parse a command from a YAML scalar."""

        match = self._COMMAND_REGEX.match(yamlScalar)
        if not match:
            raise ValueError('Line %d: %s is not a valid command syntax ' \
                '(formula "%s")' % (self._currentLineno, yamlScalar,
                    self._formulaFile))

        commandName = match.group('command')
        try:
            command = self._commands.get_command(commandName)
        except KeyError:
            raise ValueError('Line %d: Unkown command "%s" (formula "%s")' % \
                (self._currentLineno, commandName, self._formulaFile))

        try:
            argumentValues = shlex.split(match.group('argumentValues'))
        except IndexError:
            argumentValues = []
        self._validate_passed_arguments(command, argumentValues)

        providedVars = command.get_provided_variables()
        self._validate_provided_variables(command, providedVars)

        # Determine internal execution instructions of the command. These
        # instructions haven nothin to do with the comman'ds execution logic,
        # but represent instructions needed by corollary to execute an execution
        # plan and manipulate, e.g., the variable stack.
        instrBefore, instrAfter = self._internal_execution_instructions(command)
        return (instrBefore, command, argumentValues, instrAfter)

    def _validate_passed_arguments(self, command, passedArguments):
        """Validate the arguments passed to a command."""

        expectedCount = len(command.get_arguments())
        passedCount = len(passedArguments)
        if passedCount != expectedCount:
            raise ValueError('Line %d: Command "%s" takes %d argument(s), ' \
                'got %d (formula "%s")' % (self._currentLineno,
                command.get_name(), expectedCount, passedCount,
                self._formulaFile))

    def _validate_provided_variables(self, command, providedVariables):
        """Validate the variables provided by a command."""

        if self._commands.is_builtin_command(command.get_name()):
            return

        # A command cannot override variables provided by a built-in command
        builtinVars = self._commands.get_builtin_provided_variables()
        providedVarNames = [v.get_name() for v in providedVariables]
        providedBuiltins = [v for v in providedVarNames if v in builtinVars]
        if providedBuiltins:
            raise ValueError('Line %d: Command "%s" cannot provide built-in ' \
                'variable(s) "%s" (formula "%s")' % (self._current_lineno,
                command.get_name(), ', '.join(providedBuiltins),
                self._formulaFile))

    def _internal_execution_instructions(self, command):
        """Determine the internal execution instructions of a command.

        Internal execution instructions may only originate from a built-in
        command. This method returns a tuple. Its first element determines
        execution instructions to be executed _before_ the command. Its second
        element determines instructions to be executed _after_ the command.
        """

        if not self._commands.is_builtin_command(command.get_name()):
            return (None, None)

        if command.get_name() == _GroupCommand.NAME:
            return (self._GROUP_ENTRY, self._GROUP_EXIT)
        elif command.get_name() == _ModuleCommand.NAME:
            return (self._MODULE_ENTRY, self._MODULE_EXIT)
        else:
            return (None, None)

    def _insert_before_execution_instruction_into_plan(self, executionPlan,
        instrBefore):
        """Insert before execution instructions into the execution plan."""

        executionPlan[self._currentLineno][0].append(instrBefore)

    def _insert_after_execution_instruction_into_plan(self, executionPlan,
        nestingLevel, yamlEntries, instrsAfter):
        """Insert after execution instructions into the execution plan."""

        # After execution instructions are executed when the command ends, i.e.,
        # at a line number whose nesting level is lesser or equal to the nesting
        # level of the command. For example, after execution instructions of a
        # group are inserted into the execution plan when the group is left.
        nextLinenos = [l for l in sorted(yamlEntries.keys())
            if l > self._currentLineno]
        for nextLineno in nextLinenos:
            lineLevel = yamlEntries[nextLineno][1]
            if lineLevel <= nestingLevel:
                # After instructions become the first instructions to be
                # executed at the same or next lower nesting level
                executionPlan[nextLineno] = ([instrsAfter], None, [], [])
                return

        # There are not line numbers following the current one, i.e., the
        # command is the last one of the current formula. In this case, the
        # after execution instructions become the instructions to be executed
        # after the command, instead of before the command on the next nesting
        # level (see above).
        executionPlan[self._currentLineno][2].append(instrsAfter)

    def _validate_scoping(self):
        """Validate scoping within the formula."""

        self._iterate_execution_plan(ExecutionPlanScopingValidator())

    def _iterate_execution_plan(self, iterator):
        """Iterate the formula's execution plan.

        This is a template method, whose behavior can be influenced by
        ExecutionPlanIterator implementations.
        """

        self._setup_scope()
        self._setup_variable_stack()

        # Iterator: Pass formula file
        iterator.set_formula_file(self._formulaFile)

        for self._current_lineno, commandInfo in self._executionPlan:
            # Iterator: Pass line number
            iterator.set_lineno(self._current_lineno)

            (instrsBefore, command, argumentValues, instrsAfter) = commandInfo
            # For each command to be iterated, create a fresh instance. That is,
            # commands are always considered stateless.
            newCommandInstance = command.new_instance()

            # Iterator: Pass command instance
            iterator.set_command(newCommandInstance)
            # Iterator: Pass target directory
            iterator.set_target_directory(
                os.path.realpath(self._targetDirectory)
            )
            # Iterator: Pass command's argument values
            iterator.set_argument_values(argumentValues)

            self._determine_current_scope(instrsBefore)
            # Iterator: Pass current scope
            iterator.after_scope_set(self._currentScope)

            self._execute_instruction_on_variable_stack(instrsBefore)
            # Iterator: Pass current scope's variables
            iterator.after_variable_stack_preparation(
                self._visibleVariables[self._currentScope]
            )

            # Put provided variables of a command on the current scope's
            # variable stack
            for v in newCommandInstance.get_provided_variables():
                providedValue = iterator.get_provided_variable_value(
                    v.get_name()
                )
                self._put_value_on_variable_stack(v, providedValue)

            iterator.after_provided_variables_on_stack(
                self._visibleVariables[self._currentScope]
            )

            self._execute_instruction_on_variable_stack(instrsAfter)
            self._determine_current_scope(instrsAfter)

    def _setup_scope(self):
        """Setup scope stack."""

        self._currentScope = CommandScope.GLOBAL
        self._scopeStack = [self._currentScope]

    def _setup_variable_stack(self):
        """Setup variable stack per possible scope."""

        self._visibleVariables = {
            CommandScope.GLOBAL: {},
            CommandScope.GROUP: {},
            CommandScope.MODULE: {}
        }

    def _determine_current_scope(self, executionInstructions):
        """Determine current scope from the given execution instructions.

        This method also manipulates the scope stack depending on the given
        execution instructions.
        """

        for instruction in executionInstructions:
            if instruction == self._GROUP_ENTRY:
                self._currentScope = CommandScope.GROUP
                self._scopeStack.insert(0, self._currentScope)
            elif instruction == self._GROUP_EXIT:
                self._currentScope = self._scopeStack.pop(0)
            elif instruction == self._MODULE_ENTRY:
                self._currentScope = CommandScope.MODULE
                self._scopeStack.insert(0, self._currentScope)
            elif instruction == self._MODULE_EXIT:
                self._currentScope = self._scopeStack.pop(0)

    def _execute_instruction_on_variable_stack(self, executionInstructions):
        """Execute internal execution instructions on the variable stack.

        The execution instructions may impact the variable stacks of more than
        one scope.
        """

        globalVars = self._visibleVariables[CommandScope.GLOBAL]
        for instruction in executionInstructions:
            # A group was entered. Copy the variables from preceding global
            # scope.
            if instruction == self._GROUP_ENTRY:
                self._copy_variables(globalVars.keys(), CommandScope.GLOBAL,
                    CommandScope.GROUP)
            # A group was exited. Remove its variables from the stack.
            elif instruction == self._GROUP_EXIT:
                self._visibleVariables[CommandScope.GROUP] = {}
            # A module. was entered. Copy the variables from preceding global
            # and group scope. Group variables may overwrite global variables,
            # if a module is contained in a group.
            elif instruction == self._MODULE_ENTRY:
                groupVars = self._visibleVariables[CommandScope.GROUP].keys()
                globalNonGroup = [g for g in globalVars if g not in groupVars]
                self._copy_variables(globalNonGroup, CommandScope.GLOBAL,
                    CommandScope.MODULE)
                self._copy_variables(groupVars, CommandScope.GROUP,
                    CommandScope.MODULE)
            # A module was exited. Remove its variables from the stack.
            elif instruction == self._MODULE_EXIT:
                self._visibleVariables[CommandScope.MODULE] = {}

    def _copy_variables(self, variableNames, fromScope, toScope):
        """Copy variable values from a scope to another scope.

        Copying is deep.
        """

        scopeVars = self._visibleVariables[fromScope]
        toCopy = [v for v in scopeVars if v in variableNames]
        for varName in toCopy:
            value = scopeVars[varName]
            self._visibleVariables[toScope][varName] = copy.deepcopy(value)

    def _put_value_on_variable_stack(self, variable, value):
        """Put a variable value on the current scope's variable stack."""

        self._visibleVariables[self._currentScope][variable.get_name()] = value

    def execute(self):
        """Execute the execution plan."""

        self._iterate_execution_plan(ExecutionPlanExecutor())

class ExecutionPlanIterator(ABC):
    """Abstract baseclass for execution plan iterators."""

    def after_scope_set(self, currentScope):
        """Callback: Current scope was determined."""

        pass

    def after_variable_stack_preparation(self, scopeVariables):
        """Callback: The variable stack for the current scope was prepared."""

        pass

    def get_provided_variable_value(self, variableName):
        """Get the value of a provided variable."""

        return None

    def after_provided_variables_on_stack(self, scopeVariables):
        """Callback: Provided variable values were put on the stack."""

        pass

    def set_formula_file(self, formulaFile):
        """Set the execution plan's formula file."""

        self._formulaFile = formulaFile

    def get_formula_file(self):
        """Get the execution plan's formula file."""

        return self._formulaFile

    def set_lineno(self, lineno):
        """Set current line number."""

        self._lineno = lineno

    def get_lineno(self):
        """Get current line number."""

        return self._lineno

    def set_command(self, command):
        """Set current command."""

        self._command = command

    def get_command(self):
        """Get current command."""

        return self._command

    def set_argument_values(self, argumentValues):
        """Set current command's argument values."""

        self._argumentValues = argumentValues

    def get_argument_values(self):
        """Get current command's argument values."""

        return self._argumentValues

    def set_target_directory(self, targetDirectory):
        """Set target directory passed to corollary."""

        self._targetDirectory = targetDirectory

    def get_target_directory(self):
        """Get the target directory."""

        return self._targetDirectory

class ExecutionPlanScopingValidator(ExecutionPlanIterator):
    """An execution plan iterator to validate a plan's scoping."""

    def after_scope_set(self, currentScope):
        """Validate the current command's scope."""

        self._currentScope = currentScope
        commandScope = self.get_command().get_maximum_scope()
        if commandScope.value < currentScope.value:
            raise ValueError('Line %d: Maximum scope of command "%s" is ' \
                '"%s", but the current scope is "%s" (formula "%s")' % \
                (self.get_lineno(), self.get_command().get_name(), commandScope,
                    self._currentScope, self.get_formula_file()))

    def after_provided_variables_on_stack(self, scopeVariables):
        """Validate variable scopes."""

        command = self.get_command()
        missingRequiredVariableNames = [ rv
            for rv in command.get_required_variable_names()
            if rv not in scopeVariables
        ]
        if missingRequiredVariableNames:
            missingStr = ', '.join(missingRequiredVariableNames)
            visibleStr = ', '.join('"{0}"'.format(k) \
                for k in scopeVariables.keys())
            raise ValueError('Line %d: Command "%s" requires variables ' \
                '"%s", but they are not provided on the current scope ' \
                '"%s". Visible variables are %s (formula "%s")' % \
                (self.get_lineno(), command.get_name(), missingStr,
                    self._currentScope, visibleStr, self.get_formula_file()))

class ExecutionPlanExecutor(ExecutionPlanIterator):
    """An execution plan iterator for command execution."""

    def after_variable_stack_preparation(self, scopeVariables):
        """Execute the current command."""

        # Execute the command
        command = self.get_command()
        command.set_scope_variables(scopeVariables)
        command.set_target_directory(self.get_target_directory())
        argumentValues = self.get_argument_values()
        argumentValuesDict = self._argument_values_as_dict(argumentValues)
        self._return_values = command.execute(argumentValuesDict) or {}

        # Validate the correct execution of the command based on its
        # specification
        self._validate_return_values_type()
        self._validate_return_and_provided_values_consistency()
        self._validate_missing_return_values()

    def _argument_values_as_dict(self, argumentValues):
        """Transform argument values to a dict.

        The dict representation is used to pass argument values in the form
        "argument name:argument value" to the command.
        """

        command = self.get_command()
        argumentNames = [a.get_name() for a in command.get_arguments()]
        return {argumentNames[i]:argumentValues[i]
            for i in range(len(argumentNames))}

    def _validate_return_values_type(self):
        """Validate the type of a command's return value.

        Commands are required to return a dict in the form
        "provided variable name:variable value". That is, a command's return
        values are equivalent to the variables it specified to provide.
        """

        if not isinstance(self._return_values, dict):
            command = self.get_command()
            raise ValueError('Line %d: Command "%s" is expected to return ' \
                'provided variables and their values as a dictionary, but ' \
                'instead returned "%s" of type %s (formula "%s")' % \
                (self.get_lineno(), command.get_name(), self._return_values,
                    type(self._return_values).__name__,
                    self.get_formula_file()))

    def _validate_return_and_provided_values_consistency(self):
        """Validate consistency of command specification and return values.

        A command must not return more values than it specified to provide
        variables.
        """

        command = self.get_command()
        if self._return_values and not command.get_provided_variables():
            returnValuesStr = ', '.join(['"%s" (value = %s)' % (str(k), str(v))
                for k, v in self._return_values.items()])
            raise ValueError('Line %d: Command "%s" did not promise to ' \
                'provide variables, but instead returned variables %s ' \
                '(formula "%s")' % (self.get_lineno(), command.get_name(),
                returnValuesStr, self.get_formula_file()))

    def _validate_missing_return_values(self):
        """Validate that no return value is missing.

        A command must return a value for each provided variable it
        specified.
        """

        command = self.get_command()
        missingReturnValues = [v.get_name()
            for v in command.get_provided_variables()
            if v.get_name() not in self._return_values
        ]
        if missingReturnValues:
            missingReturnValuesStr = ', '.join('"{0}"'.format(v)
                for v in missingReturnValues)
            raise ValueError('Line %d: Command "%s" promised to provide ' \
                'values for variables %s, but failed to do so ' \
                '(formula "%s")' % (self.get_lineno(), command.get_name(),
                missingReturnValuesStr, self.get_formula_file()))

    def get_provided_variable_value(self, variableName):
        """Get the value of the given provided variable."""

        return self._return_values[variableName]

def _error_and_exit(message, error=None, suffix=' Exiting.'):
    """Log an error message and exit corollary with a non-zero return code."""

    logger = logging.getLogger()
    if logger.level == logging.DEBUG and error:
        raise error
    else:
        logger.error(message + suffix)
        sys.exit(4)

if __name__ == '__main__':
    """corollary main logic."""

    logging.basicConfig(format=None, level=logging.DEBUG)

    commandline = Commandline()
    commandline.parse_arguments()

    if not os.path.isdir(commandline.target_directory):
        _error_and_exit('Target directory "%s" does not exist.' % \
            commandline.target_directory)

    # Retrieve commands
    try:
        commands = Commands(commandline.command_directory)
    except ModuleNotFoundError as e:
        _error_and_exit('Could not load commands from directory "%s". Does ' \
            'the directory exist?' % commandline.command_directory, e)
    except ValueError as e:
        _error_and_exit('An unexpected error occurred: %s.' % str(e), e)

    # Parse formula.
    try:
        formula = Formula(commandline.formula, commands)
    except FileNotFoundError as e:
        _error_and_exit('Could not load formula "%s". Does the file exist?' %
            commandline.formula, e)
    except yaml.parser.ParserError as e:
        _error_and_exit('Error while parsing formula "%s": %s.' %
            (commandline.formula, e), e, suffix='\nExiting.')
    except ValueError as e:
        _error_and_exit('An unexpected error occurred: %s.' % str(e), e)

    # Execute plan
    try:
        plan = ExecutionPlan(commands, formula, commandline.target_directory)
        plan.execute()
    except ValueError as e:
        _error_and_exit('An unexpected error occurred: %s.' % str(e), e)