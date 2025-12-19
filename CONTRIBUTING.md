# Contributing to the Project

Thank you for considering contributing to our project! Your help and involvement are highly appreciated.
This guide will help you get started with the contribution process.

## Table of Contents

1. [Fork the Repository](#fork-the-repository-)
2. [Clone Your Fork](#clone-your-fork-)
3. [Create a New Branch](#create-a-new-branch-)
4. [Submitting Changes](#submitting-changes-)
5. [Create a Pull Request](#create-a-pull-request-)
6. [Coding Style](#coding-style-)
7. [Keep It Simple](#keep-it-simple-)

## Fork the Repository 🍴

Start by forking the repository. You can do this by clicking the "Fork" button in the
upper right corner of the repository page. This will create a copy of the repository
in your GitHub account.

## Clone Your Fork 📥

Clone your newly created fork of the repository to your local machine with the following command:

```bash
git clone https://github.com/your-username/google-cloud-github-runner.git
```

## Create a New Branch 🌿

Create a new branch for the specific issue or feature you are working on.
Use a descriptive branch name:

```bash
git checkout -b "feature-or-issue-name"
```

## Submitting Changes 🚀
Make your desired changes to the codebase.

Stage your changes using the following command:

```bash
git add .
```

Commit your changes with a clear and concise commit message:

```bash
git commit -m "A brief summary of the commit."
```

## Create a Pull Request 🌟

Go to your forked repository on GitHub and click on the "New Pull Request" button.
This will open a new pull request to the original repository.

## Coding Style 📝

Please follow these coding style rules to ensure consistency and maintainability:

### Python
- **Linter:** Code must pass `flake8` with the following settings:
  - `--max-line-length=127`
  - Ignore `W292` (no new line at end of file) and `W503` (line break before binary operator).
- **Indentation:** Use **spaces**.
- **Formatting:** No trailing whitespace.

### Terraform
- **Format:** Run `terraform fmt -recursive` on the `gcp` directory.
- **Linting & Security:** Code should pass `tflint` and `tfsec`.
- **Indentation:** Use **spaces**.

### Bash / Shell Scripts
- **Linter:** Check all scripts with `shellcheck`.
- **Indentation:** Use **tabs**.

## Keep It Simple 👍

Simplicity is key. When making changes, aim for clean, easy-to-understand code that benefits all users.

Thank you for your contribution! ❤️
