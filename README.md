# corollary - Your Simple Command Executor

`corollary` is a simple Python-based command executor. It loads available commands from Python submodules in a specified directory at runtime and executes them one by one as determined by a given YAML file.

It was originally invented to automate version propagation in the release engineering of projects that rely on Maven, OSGi bundles, and/or Gradle as their build management systems. With `corollary`, version propagation can be automated by using a dead-simple YAML-based syntax to run file manipulation commands line by line.

`corollary` is invoked from the command-line as follows:  
`./corollary.py -c $COMMAND_DIR -f $YAML_FILE -t $TARGET_DIR`

To get an idea, on how custom `corollary` commands to be loaded at runtime can be implemented, refer to the `lemma.py` file in the `comands` sub-directory. It implements commands such as:  
- `mvn_tycho_set_version`: Use the [Tycho Versions Plugin](https://www.eclipse.org/tycho/sitedocs/tycho-release/tycho-versions-plugin/plugin-info.html) to update the version of a Maven POM.
- `osgi_update_bundle_version`: Update the `Bundle-Version` key in an OSGi manifest.
- `update_properties_file`: Update arbitrary values in a Java properties file.

Moreover, the user can be queried about the version to be used (`ask_for_version`) and if it's a snapshot release (`ask_for_snapshot`).

The following YAML file instructs `corollary` to (i) query the user for version and snapshot information; (ii) update the modules in the "Eclipse Plugins" group via `mvn_tycho_set_version` (module `foo.bar`) and `osgi_update_bundle_version` (module `osgi.bundle`); and (iii) update the module in the "Gradle Modules" group by directly manipulating its `gradle.properties` file.

```yaml
- ask_for_version
- ask_for_snapshot
- ask_for_continuation version
- group "Eclipse Plugins":
  - module foo.bar:
    - mvn_tycho_set_version
  - module osgi.bundle:
    - osgi_update_bundle_version
- group "Gradle Modules":
  - module gradle.project:
    - update_properties_file "gradle.properties" "version" version
```

`corollary` makes use of implicit variables to be provided and required by custom commands. For instance, the implicit `version` variable in the example YAML-based script above is provided by the `ask_for_version` command and used by all subsequent commands. Moreover, modules are interpreted as directories within the `$TARGET_DIR` passed to `corollary` via the command-line.
