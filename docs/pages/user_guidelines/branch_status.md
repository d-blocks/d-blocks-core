# Feature: Git Branch Status Analysis (`dbee branch-status`)

## Overview

The `branch-status` command provides comprehensive Git branch analysis, offering detailed insights into branch relationships, merge status, and creation dates. This feature is essential for maintaining clean Git workflows and understanding branch landscapes in d-blocks projects.

## Key Features

### 🌿 **Comprehensive Branch Analysis**
- Display both local and remote branches with detailed information
- Show branch type, last commit hash, author, and timestamps
- Track branch creation dates with accurate historical analysis
- Identify merge status using sophisticated detection algorithms

### 🔄 **Advanced Merge Detection**
- **Standard Merge Detection**: Uses `git branch --merged` for conventional merges
- **Squash Merge Detection**: Pattern matching for squash merges with branch name variations
- **Cherry-pick Detection**: Identifies rebased or cherry-picked commits
- **Branch Movement Tracking**: Detects activity after merge completion

### 📅 **Accurate Creation Date Tracking**
- **Master Branch**: Uses first commit in repository for accurate historical dating
- **Develop Branch**: Uses second commit (typical GitFlow pattern)
- **Feature Branches**: Uses merge-base analysis for precise creation dates

### 🎨 **Rich Console Output**
- Beautiful table formatting with color-coded status indicators
- Summary statistics showing branch counts and cleanup suggestions
- Professional presentation suitable for team collaboration

## Usage

### Basic Commands

```bash
# Show all branches (local and remote)
dbee branch-status

# Show only remote branches
dbee branch-status --remote

# Show only local branches
dbee branch-status --no-remote
```

### Command Options

- `--remote`: Display only remote branches
- `--no-remote`: Display only local branches (exclusive with `--remote`)
- `--help`: Show detailed help information

## Sample Output

```
                                Repository Branches (Remote)
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Branch Name                     ┃ Type   ┃ Last Commit ┃ Author         ┃ Creation Date ┃ Last Commit Date ┃ Merged Status ┃ Merge Details          ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━┩
│ origin/feature/new-database     │ Remote │ 2b4a8bf5    │ developer      │ 2025-09-17    │ 2025-09-18 11:44 │ ○ Active      │ Not merged             │
│ origin/develop                  │ Remote │ 7561c3c0    │ developer      │ 2025-01-25    │ 2025-09-18 09:54 │ ○ Active      │ Not merged             │
│ origin/feature/table-migration  │ Remote │ 1a7ccd31    │ developer      │ 2025-09-04    │ 2025-09-17 15:45 │ ✓ Merged      │ → develop (2025-09-18) │
│ origin/master                   │ Remote │ 2b745740    │ developer      │ 2025-01-25    │ 2025-05-29 18:34 │ ○ Active      │ Not merged             │
└─────────────────────────────────┴────────┴─────────────┴────────────────┴───────────────┴──────────────────┴───────────────┴────────────────────────┘

Summary: 4 total branches, 3 active, 1 merged
💡 Consider cleaning up 1 merged branch(es)
```

## Use Cases

### Development Team Workflows

#### **Branch Cleanup Management**
```bash
# Identify merged branches ready for deletion
dbee branch-status --remote

# Look for branches with "✓ Merged" status
# These can typically be safely deleted from remote
```

#### **Release Planning**
```bash
# Review all active feature branches before release
dbee branch-status

# Check creation dates to identify long-running features
# Verify merge status to track feature completion
```

#### **Code Review Process**
```bash
# Understand branch relationships before code review
dbee branch-status --remote

# Check merge details to see integration history
# Verify branch freshness with last commit dates
```

### DevOps & CI/CD Integration

#### **Pipeline Automation**
```bash
# Check branch status in CI/CD scripts
dbee branch-status --remote | grep "Active"

# Identify branches that need attention
# Automate cleanup of merged branches
```

#### **Environment Synchronization**
```bash
# Verify Git state before environment deployment
dbee branch-status

# Ensure target branches are in expected state
# Track deployment readiness across branches
```

#### **Release Management**
```bash
# Monitor feature branch completion
dbee branch-status --remote

# Track merge progress for sprint planning
# Identify blocking branches for release
```

### Project Management

#### **Sprint Tracking**
- Monitor feature branch progress with creation dates
- Track completion status with merge indicators
- Identify stale branches that may need attention

#### **Technical Debt Management**
- Find long-running branches that may need refactoring
- Identify branches with outdated last commit dates
- Plan cleanup activities based on merge status

#### **Team Collaboration**
- Share branch landscape visibility across team members
- Understand project state at a glance
- Coordinate branch naming and lifecycle management

## Best Practices

### 🧹 **Regular Branch Cleanup**
1. Run `dbee branch-status --remote` weekly
2. Identify branches marked as "✓ Merged"
3. Safely delete merged remote branches after verification
4. Keep the repository clean and navigation-friendly

### 📊 **Sprint Planning Integration**
1. Use creation dates to identify long-running features
2. Check merge status to track completion progress
3. Review last commit dates to find inactive branches
4. Plan branch consolidation activities

### 🔄 **CI/CD Integration**
1. Add branch status checks to deployment pipelines
2. Automate alerts for stale branches
3. Include branch cleanup in regular maintenance tasks
4. Use merge status for automated testing triggers

### 👥 **Team Coordination**
1. Share branch status reports in team meetings
2. Use merge details to understand integration flow
3. Coordinate feature branch lifecycle management
4. Establish branch naming conventions for better tracking

## Integration with d-blocks Workflow

The `branch-status` feature integrates seamlessly with other d-blocks commands:

### **With Package Creation**
```bash
# Check branch status before creating packages
dbee branch-status

# Verify merge status of target branches
# Ensure deployment readiness
```

### **With Environment Deployment**
```bash
# Review branch state before environment sync
dbee branch-status --remote

# Confirm target branch freshness
# Track deployment source integrity
```

### **With Extraction Features**
```bash
# Understand repository state before extraction
dbee branch-status

# Plan extraction strategy based on branch landscape
# Coordinate with active development branches
```

## Troubleshooting

### **Common Issues**

#### **Missing Creation Dates**
- Ensure you have full Git history available
- Shallow clones may not have complete history for accurate dating
- Use `git fetch --unshallow` if needed

#### **Incorrect Merge Detection**
- Squash merges may require branch name pattern matching
- Check that branch naming follows consistent conventions
- Verify Git history integrity for accurate detection

#### **Performance with Large Repositories**
- Command may take longer with repositories having many branches
- Consider filtering with `--remote` or `--no-remote` options
- Large Git histories require more processing time

### **Getting Help**
```bash
# Show detailed command help
dbee branch-status --help

# Check d-blocks general help
dbee --help
```

---

This feature significantly enhances d-blocks' Git integration capabilities, providing development teams with powerful tools for repository management and workflow optimization.
