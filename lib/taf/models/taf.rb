require 'fileutils'
require_relative '../markdown_adapter'
require_relative '../taf_helper'
require_relative '../terminal_presenter'
require_relative 'todo'

class Taf
  def initialize(file)
    @file = file
    @taf = MarkdownAdapter.read(file)
    assign_indices
    @presenter = TerminalPresenter.new
  end

  # Creates a backup of the file
  def self.backup(file)
    FileUtils.cp(file, "#{file}.backup") if File.exist?(file)
  end

  # Restores the backup file and deletes it
  def self.restore(file)
    backup_file = "#{file}.backup"
    unless File.exist?(backup_file)
      raise ArgumentError, "No backup file found"
    end

    FileUtils.cp(backup_file, file)
    File.delete(backup_file)
  end

  # Adds a new item
  def add_todo(text, tag: nil, parent_id: nil)
    # Avoids flag typos
    raise ArgumentError, "Text must be #{Todo::MIN_LENGTH} or more characters" unless text.size >= Todo::MIN_LENGTH

    # Default tag if neither tag nor parent specified
    if tag.nil? && parent_id.nil?
      tag = TafHelper::DEFAULT_TAG
    end

    changed = []
    if parent_id
      parent_item = find_item_by_id(parent_id)
      unless parent_item
        raise ArgumentError, "Parent with id #{parent_id} not found"
      end

      new_item = Todo.new(
        status: "todo",
        text: text,
        children: [],
        parent: parent_item
      )
      parent_item.children << new_item
      changed = mark_ancestors_todo(parent_item)
    else
      new_item = Todo.new(
        status: "todo",
        text: text,
        children: []
      )
      if @taf[tag]
        # Tag exists, append to root level
        @taf[tag] << new_item
      else
        # Create new tag
        @taf[tag] = [new_item]
      end
    end

    changed << new_item
    assign_indices
    save

    changed.map(&:signature)
  end

  # Shows given tag and its items
  def show_tag(tag, highlight_signatures: nil)
    @taf.each do |key, items|
      next unless key == tag

      @presenter.display_tag(key)
      items.each do |item|
        display_item_recursive(item, 0, highlight_signatures)
      end
      puts ""
    end
  end

  # Shows all tags and items
  def show_all(highlight_signatures: nil)
    @taf.each do |key, items|
      @presenter.display_tag(key)
      items.each do |item|
        display_item_recursive(item, 0, highlight_signatures)
      end
      puts ""
    end
  end

  # Recursively displays an item and its children with proper indentation
  def display_item_recursive(item, indent_level, highlight_signatures)
    @presenter.display_todo(item, indent_level, highlighted: highlight_signatures&.include?(item.signature))
    item.children.each do |child|
      display_item_recursive(child, indent_level + 1, highlight_signatures)
    end
  end

  # Toggles the status of the item
  # Toggles ancestors and descendants accordingly
  def toggle(item)
    item.status = item.status == "done" ? "todo" : "done"

    affected_items = [item]
    if item.status == "done"
      affected_items.concat(mark_descendants_done(item))
    elsif item.parent
      affected_items.concat(mark_ancestors_todo(item.parent))
    end

    save
    affected_items.map(&:signature)
  end

  # Recursively marks all descendants as done and returns those that changed
  def mark_descendants_done(item)
    changed = []
    item.children.each do |child|
      changed << child if child.status != "done"
      child.status = "done"
      changed.concat(mark_descendants_done(child))
    end
    changed
  end

  # Recursively marks all ancestors as todo and returns those that changed
  def mark_ancestors_todo(item)
    changed = []
    current = item
    while current
      changed << current if current.status != "todo"
      current.status = "todo"
      current = current.parent
    end
    changed
  end

  # Deletes the item (and all its children)
  def delete(item)
    if item.parent
      # Remove from parent's children
      item.parent.children.delete(item)
    else
      # Remove from root level
      @taf.each_value do |items|
        if items.delete(item)
          break
        end
      end
    end

    save
  end

  # Finds a todo item by its index across all tags (searches recursively)
  def find_item_by_id(id)
    @taf.each_value do |items|
      items.each do |item|
        result = find_in_subtree(item, id)
        return result if result
      end
    end
    nil
  end

  # Sorts all items (todo items before done items) and saves
  def cleanup
    # Sort items: within each parent, todo items before done items
    @taf.each_value do |items|
      items.each do |item|
        sort_children_recursive(item)
      end
      # Sort root level items
      items.sort_by! { |item| item.status == "done" ? 1 : 0 }
    end

    save
  end

  # Deletes all done items (and their children) and saves
  def purge
    @taf.each_value do |items|
      items.reject! { |item| item.status == "done" }
      items.each do |item|
        purge_done_children(item)
      end
    end

    save
  end

  private

  # Recursively removes done children from an item
  def purge_done_children(item)
    item.children.reject! { |child| child.status == "done" }
    item.children.each do |child|
      purge_done_children(child)
    end
  end

  # Recursively searches for an item in a subtree
  def find_in_subtree(item, id)
    return item if item.idx == id

    item.children.each do |child|
      result = find_in_subtree(child, id)
      return result if result
    end
    nil
  end

  # Removes empty tags and writes to file
  def save
    @taf.delete_if { |_tag, items| items.empty? }
    self.class.backup(@file)
    MarkdownAdapter.write(@file, @taf)
  end

  # Recursively sorts children: todo before done
  def sort_children_recursive(item)
    item.children.sort_by! { |child| child.status == "done" ? 1 : 0 }
    item.children.each do |child|
      sort_children_recursive(child)
    end
  end

  # Assigns sequential indices to all todo items using depth-first traversal
  def assign_indices
    idx = 0
    @taf.each_value do |items|
      items.each do |item|
        idx = assign_index_recursive(item, idx)
      end
    end
  end

  # Recursively assigns indices in depth-first order
  def assign_index_recursive(item, idx)
    idx += 1
    item.idx = idx
    item.children.each do |child|
      idx = assign_index_recursive(child, idx)
    end
    idx
  end
end
