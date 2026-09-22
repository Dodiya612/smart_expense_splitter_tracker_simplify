# Contributing Guide

This guide explains the basic Git workflow for contributing to the **Smart Expense Splitter & Tracker** project.

## 1. Clone the Repository

You only need to do this once.

```bash
git clone https://github.com/Dodiya612/smart_expense_splitter_tracker_simplify.git
cd smart_expense_splitter_tracker_simplify
```

Open the project in VS Code:

```bash
code .
```

## 2. Get the Latest Code

Before starting a new task:

```bash
git checkout main
git pull origin main
```

This makes sure you are working with the latest version.

## 3. Create a Branch

**Do not work directly on `main`.**

Create a new branch for your task:

```bash
git checkout -b feature/your-task-name
```

For example:

```bash
git checkout -b feature/expense-tracking
```

Examples:

```text
feature/login
feature/expense-tracking
feature/group-splitting
feature/budget
feature/analytics
feature/ai
```

## 4. Make Your Changes

Work only on your assigned task.

Check your changes with:

```bash
git status
```

To see exactly what changed:

```bash
git diff
```

Test your changes before pushing them.

## 5. Commit Your Changes

Add your changes:

```bash
git add .
```

Commit them with a clear message:

```bash
git commit -m "Add expense tracking"
```

Good commit messages:

```text
Add login page
Add expense tracking
Fix expense calculation
Update budget validation
```

## 6. Push Your Branch

Push your branch to GitHub:

```bash
git push -u origin feature/expense-tracking
```

Replace `feature/expense-tracking` with your branch name.

## 7. Create a Pull Request

Open the repository on GitHub:

https://github.com/Dodiya612/smart_expense_splitter_tracker_simplify

Create a **Pull Request** from your branch into `main`.

For example:

```text
feature/expense-tracking → main
```

In the Pull Request, briefly mention:

- What you implemented
- What you tested
- Any known issues

## 8. After the Pull Request Is Merged

Update your local `main` branch:

```bash
git checkout main
git pull origin main
```

For your next task, create a new branch:

```bash
git checkout -b feature/your-next-task
```

## Basic Workflow

```text
Pull latest main
      ↓
Create branch
      ↓
Make changes
      ↓
Test
      ↓
Commit
      ↓
Push
      ↓
Create Pull Request
      ↓
Review
      ↓
Merge into main
```

## Important Rules

- Do not work directly on `main`.
- Create a new branch for each task.
- Test your changes before creating a Pull Request.
- Keep commits related to your task.
- Do not commit passwords, API keys, or `.env` files.
- Do not make unrelated changes to another member's work.
- If you are unsure about a Git error or merge conflict, ask the team before making changes.

## Common Commands

```bash
git status
git branch
git checkout main
git pull origin main
git checkout -b <branch-name>
git add .
git commit -m "Your commit message"
git push
```
