# Contributing to NEXYROTH

Thank you for your interest in contributing to NEXYROTH. This document outlines the process for contributing code, reporting bugs, and proposing new features.

## Getting Started

Clone the repository and ensure you have Python 3.10+ installed. All scripts use only standard library modules plus `requests` and `pandas`, which are listed in `docs/requirements.txt`.

```bash
git clone https://github.com/big-main/nexyroth.git
cd nexyroth
pip install requests pandas
```

## Security Notice

**Never commit API keys, secrets, or private keys.** All credentials must be loaded from environment variables or files under `~/.secrets/`. The `.gitignore` already excludes common secret file patterns. If you accidentally commit a secret, rotate it immediately.

## Development Workflow

1. Fork the repository and create a feature branch from `main`.
2. Make your changes, following the code style of the existing scripts (PEP 8, type hints where practical).
3. Test your script manually against the Bitunix testnet or with dry-run mode before submitting.
4. Update `CHANGELOG.md` under the `[Unreleased]` section describing your change.
5. Open a pull request against `main` with a clear description of what changed and why.

## Pull Request Guidelines

Pull requests should be focused and atomic — one feature or fix per PR. Include the following in your PR description:

- What the change does
- How it was tested
- Any risk to existing live trading scripts

## Reporting Bugs

Use the GitHub issue tracker with the **Bug Report** template. Include the script name, the error message or unexpected behavior, and the relevant log lines from the script's `.log` file.

## Proposing Features

Open a **Feature Request** issue describing the trading strategy, indicator, or infrastructure improvement you want to add. Include the expected behavior, the tokens or timeframes it targets, and any backtesting results if available.

## Code Style

Scripts follow a consistent pattern: constants at the top, auth helpers, market data helpers, indicator functions, signal logic, execution, and a `main()` entry point. New scripts should follow this same structure for consistency.
