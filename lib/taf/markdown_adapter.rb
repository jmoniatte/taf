module MarkdownAdapter
  require_relative 'taf_helper'
  require_relative 'models/todo'

  # Markdown format constants
  TAG_PREFIX = "#".freeze
  TODO_PREFIX = "- [ ]".freeze
  DONE_PREFIX = "- [x]".freeze
  INDENT_SIZE = 2  # Number of spaces per indent level

  # Reads markdown and returns data as a tree structure
  def self.read(file)
    return {} unless File.exist?(file)

    rows = File
      .readlines(file)
      .map(&:rstrip)
      .reject { |line| line.nil? || line.empty? }

    {}.tap do |data|
      tag = TafHelper::DEFAULT_TAG
      # Stack to track parent at each indent level
      stack = []

      rows.each do |row|
        if row.start_with?("#{TAG_PREFIX} ")
          tag = row.delete_prefix("#{TAG_PREFIX} ")
          data[tag] ||= []
          stack = []  # Reset stack for new tag
        elsif tag.nil?
          next
        else
          # Calculate indent level from leading spaces
          leading_spaces = row[/^\s*/].length
          indent_level = leading_spaces / INDENT_SIZE
          stripped_row = row.lstrip

          # Trim stack to current indent level
          stack = stack[0...indent_level]

          # Determine parent
          parent = indent_level > 0 ? stack[indent_level - 1] : nil

          # Create the item
          status = stripped_row.start_with?("#{TODO_PREFIX} ") ? "todo" : "done"
          prefix = status == "todo" ? TODO_PREFIX : DONE_PREFIX
          item = Todo.new(
            status: status,
            text: stripped_row.delete_prefix("#{prefix} "),
            children: [],
            parent: parent
          )

          # Add to parent's children or to root
          if indent_level == 0
            data[tag] << item
          else
            parent.children << item
          end

          # Push current item onto stack
          stack[indent_level] = item
        end
      end
    end
  end

  # Writes data to markdown file (flattens tree structure)
  def self.write(file, data)
    rows = []
    data.each do |tag, items|
      rows << "#{TAG_PREFIX} #{tag}"
      items.each do |item|
        flatten_item(item, 0, rows)
      end
    end
    File.write(file, rows.join("\n"))
  end

  # Recursively flattens a tree item and its children
  def self.flatten_item(item, indent_level, rows)
    prefix = item.status == "todo" ? TODO_PREFIX : DONE_PREFIX
    indent = ' ' * (indent_level * INDENT_SIZE)
    rows << "#{indent}#{prefix} #{item.text}"

    # Recursively add children
    item.children.each do |child|
      flatten_item(child, indent_level + 1, rows)
    end
  end
end
