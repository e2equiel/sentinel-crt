# Sentinel Settings

This folder hosts YAML configuration fragments that complement the legacy
`config.py` file. The loader merges values in the following order:

1. Built-in defaults shipped with the application.
2. YAML files in this `settings/` directory (core/priorities/modules/services).
3. Values declared in `config.py` (if present).

You can override or extend screen modules by dropping additional files under
`settings/modules/`. Each file should expose the Python import path of the
module implementation and any configuration payload it requires.

## Migrating existing ``config.py`` files

To convert a legacy installation that only relied on ``config.py`` run:

```bash
python -m sentinel.tools.migrate_config --output settings
```

This command writes ``core.yaml`` and module specific YAML files without
overwriting existing ones unless ``--force`` is provided.
