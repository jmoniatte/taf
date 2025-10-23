# TAF - Travail À Faire

A simple CLI todo list manager written in Ruby.

`taf` is a lightweight command-line tool that helps you manage your todos in a markdown file. It supports hierarchical task organization with tags, parent-child relationships, and various management commands.

## Features

* Store todos in a simple markdown format
* Organize tasks with tags
* Create hierarchical todos (parent-child relationships)
* Toggle task completion status
* Undo changes with automatic backups
* Cleanup and purge completed tasks

## Installation

### Prerequisites

Ensure you have Ruby 2.6 or later installed:

```bash
ruby --version
```

### Install from RubyGems

```bash
gem install taf-cli
```

This installs the `taf` command.

### Verify Installation

```bash
taf --help
```

### Install from Source (Alternative)

If you want to install from source:

```bash
git clone https://github.com/jmoniatte/taf.git
cd taf
gem build taf.gemspec
gem install ./taf-cli-1.0.0.gem
```

## Usage

By default, `taf` uses `~/taf.md` as the todo file. You can specify a different file with the `-f` option.

### Basic Commands

**View all todos:**
```bash
taf
```

**Add a todo with a tag:**
```bash
taf Buy groceries @shopping
```

**Add a todo (uses "Untagged" as default tag):**
```bash
taf Fix the bug in authentication
```

**View todos for a specific tag:**
```bash
taf @shopping
```

**Add a child todo under a parent:**
```bash
taf Buy milk @12
# This adds "Buy milk" as a child of item @12
```

**Toggle a todo's completion status:**
```bash
taf -t @12
```

**Delete a todo:**
```bash
taf -D @12
```

**Edit the file manually:**
```bash
taf -e
# Opens the file $EDITOR (or vim by default)
```

**Undo the last change:**
```bash
taf -u
```

**Cleanup (sort todos before done items):**
```bash
taf -c
```

**Purge all completed tasks:**
```bash
taf -P
```

### Using a Custom File

```bash
taf -f /path/to/my-todos.md "New task" @work
```

## Markdown Format

The todo file is stored in a simple markdown format:

```markdown
# shopping
- [ ] Buy groceries
  - [ ] Milk
  - [x] Bread
- [x] Get coffee

# work
- [ ] Review pull request
- [ ] Write documentation
```

- Tags are markdown headers (`# tagname`)
- Uncompleted todos use `- [ ]`
- Completed todos use `- [x]`
- Child items are indented with 2 spaces per level

## Options

```
Usage: taf [options] [message]
Options:
  -f, --file FILE      Path to the taf markdown file (default: ~/taf.md)
  -h, --help           Show help
  -t @LINE_ID          Toggle status for line id
  -D @LINE_ID          Delete the specified line id
  -e, --edit           Open the file in $EDITOR for manual edits
  -u, --undo           Undo the last change
  -c, --cleanup        Sort items (todo items before done)
  -P, --purge          Delete all done items

Message:
  text @tag            Records todo for @tag
  text @ID             Records todo as child of parent ID
  @tag                 Displays todos for @tag
```

## Examples

```bash
# Start fresh
taf "Plan vacation" @personal

# Add related subtasks
taf "Book flights" @1
taf "Reserve hotel" @1
taf "Research activities" @1

# Add work tasks
taf "Review code" @work
taf "Update documentation" @work

# Mark a task as done
taf -t @2

# View all tasks
taf

# View only personal tasks
taf @personal

# Clean up completed tasks
taf -P
```

## License

MIT
