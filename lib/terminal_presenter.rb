require_relative 'ansi_colors'
require_relative 'markdown_adapter'

# Handles terminal display formatting for items
class TerminalPresenter
  # Display format constants
  TAG_PREFIX = "#".freeze
  TODO_PREFIX = "- [ ]".freeze
  DONE_PREFIX = "- [x]".freeze
  INDENT_SIZE = 2

  def display_tag(tag)
    puts "#{TAG_PREFIX} #{tag}".red
  end

  def display_todo(todo, indent_level, highlighted: false)
    # Add indentation based on tree depth
    indent = ' ' * (indent_level * INDENT_SIZE)

    prefix = case todo.status
             when "done"
               DONE_PREFIX.grey
             when "todo"
               TODO_PREFIX.default
             end

    text_colored = todo.status == "done" ? todo.text.grey : todo.text.default

    line_number = "[#{todo.idx}]".cyan
    indicator = highlighted ? " ✔".green : ""

    puts indent + [prefix, text_colored, line_number + indicator].join(" ")
  end
end
