# Application Buddy

A comprehensive project setup guide for contributors.

## Table of Contents

- [First-Time Setup](#first-time-setup)
- [Returning Contributor](#returning-contributor)
- [Important Notes](#important-notes)
- [Requirements](#requirements)

## First-Time Setup

Follow these steps if you're a new contributor or making a fresh clone of the project.

### Step 1: Clone the Repository

```bash
git clone https://github.com/<your-username>/Application_Buddy.git
cd Application_Buddy
```

### Step 2: Open in VS Code (WSL)

```bash
code .
```

> **Note**: Make sure you have the Remote - WSL extension installed in VS Code.

### Step 3: Create Virtual Environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### Step 4: Install Dependencies

```bash
pip install -r requirements.txt
```

## Returning Contributor

If you already have the project folder and just need to get back to work:

### Step 1: Navigate to Project

```bash
cd ~/projects/application_buddy/Application_Buddy
```

### Step 2: Pull Latest Changes

```bash
git pull origin main
```

### Step 3: Activate Virtual Environment

```bash
source .venv/bin/activate
```

### Step 4: Update Dependencies

```bash
pip install -r requirements.txt
```

## Important Notes

- ⚠️ Always pull latest changes before starting work
- 📦 If new dependencies were added, run `pip install -r requirements.txt`
- 🔧 If `.venv` is missing, recreate it using `python3 -m venv .venv`

## Requirements

This project requires:
- Python 3.x
- Virtual environment support
- Git
- VS Code (recommended with Remote - WSL extension for WSL users)
