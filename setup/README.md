# Files to move into place yourself

Remote tools are not allowed to write VS Code settings, GitHub workflows or Makefiles on this
laptop, so they are kept here. Run once in PowerShell from the `council` folder:

```powershell
New-Item -ItemType Directory -Force .vscode, .github\workflows | Out-Null
Copy-Item setup\vscode\*.json .vscode\
Copy-Item setup\github\tests.yml.txt .github\workflows\tests.yml
Copy-Item setup\Makefile.txt Makefile
```

| File | Goes to | What it does |
|---|---|---|
| `vscode/settings.json` | `.vscode/` | Python interpreter in `backend/.venv`, pytest in the Testing panel |
| `vscode/tasks.json` | `.vscode/` | Run tests, validate, gate report, live run (asks for your PRD) |
| `vscode/launch.json` | `.vscode/` | Debug a live run (asks for your PRD) |
| `vscode/extensions.json` | `.vscode/` | Recommended extensions |
| `github/tests.yml.txt` | `.github/workflows/tests.yml` | Runs the tests on GitHub on every push |
| `Makefile.txt` | `Makefile` | Shortcuts for Git Bash or WSL users |
