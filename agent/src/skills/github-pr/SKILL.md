---
name: github-pr
description: Submit PRs to GitHub repositories directly from the agent. Handles git operations, branch management, and PR creation.
category: tool
---
# GitHub PR Submission

## Purpose

Automate the process of creating and submitting PRs to GitHub repositories from the Vibe-Trading agent. This capability includes:

- Git repository management (cloning, committing, branching)
- PR creation and management
- Branch protection compliance
- Commit message formatting
- PR description generation

## Usage

### Initialize Repository
```
bash(command="git clone https://github.com/HKUDS/Vibe-Trading.git")
```

### Create Branch
```
bash(command="cd Vibe-Trading && git checkout -b my-feature-branch")
```

### Make Changes
```
write_file(path="Vibe-Trading/example.py", content="print('Hello World')")
```

### Commit Changes
```
bash(command="cd Vibe-Trading && git add example.py && git config user.name 'Your Name' && git config user.email 'you@example.com' && git commit -m 'Add hello world example'")
```

### Configure GitHub CLI
```
bash(command="gh auth login")
```

### Submit PR
```
bash(command="cd Vibe-Trading && gh pr create --title 'Add hello world example' --body 'This PR adds a simple hello world example'")
```

## Notes

- **Authentication**: Requires GitHub CLI (gh) to be installed and authenticated
- **PR Description**: Should include clear title, body, and references to issues if applicable
- **Branch Protection**: Ensure PRs are created from feature branches and follow repository guidelines
- **Merge Strategy**: Follows the repository's default merge strategy (usually squash or merge)

## Requirements

- GitHub CLI installed (check with `which gh`)
- Git configured with user identity (check with `git config --list`)
- Repository cloned and accessible locally
- Changes committed and pushed to remote branch

## Common Workflow

### Complete PR Process
```
# Clone repository
bash(command="git clone https://github.com/HKUDS/Vibe-Trading.git")

# Create branch
bash(command="cd Vibe-Trading && git checkout -b my-feature-branch")

# Make changes
write_file(path="Vibe-Trading/feature.py", content="""
def my_feature():
    return "This is a new feature"
""")

# Commit
bash(command="cd Vibe-Trading && git add feature.py && git commit -m 'Add my_feature function'")

# Push branch
bash(command="cd Vibe-Trading && git remote add origin https://github.com/your-username/Vibe-Trading.git && git push -u origin my-feature-branch")

# Create PR
bash(command="cd Vibe-Trading && gh pr create --title 'Add my_feature function' --body 'This PR adds a new my_feature function' --base main --head your-username:my-feature-branch")
```

## Troubleshooting

### Authentication Issues
```bash
gh auth status
```

### Push Rejected
```bash
git remote -v
git branch -v
git status
```

### PR Creation Failed
```bash
gh pr create --debug
```
