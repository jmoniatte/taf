require 'optparse'
require_relative 'models/taf'
require_relative 'lib/ansi_colors'
require_relative 'lib/taf_helper'

# Handles CLI argument parsing and command execution
class CLI
  def initialize(args)
    @args = args
    @mode = :default
    @file = nil
    @message = nil
    @taf = nil
  end

  def run
    parse_options
    validate_options
    execute_command
  end

  private

  def parse_options
    parser = create_option_parser

    begin
      parser.parse!(@args)
      # Only set @message from remaining args if not already set by option handler
      @message ||= @args.join(" ")
    rescue OptionParser::InvalidOption, OptionParser::MissingArgument => e
      puts e.message.red
      puts parser.help.red
      exit 1
    end
  end

  def create_option_parser
    OptionParser.new do |opts|
      opts.banner = "Usage: taf [options] [message]"
      opts.separator "Options:"

      opts.on("-f FILE", "--file FILE", "Path to the taf markdown file (default: ~/taf.md)") do |file|
        @file = file
      end

      opts.on("-h", "--help", "Show help") do
        @mode = :help
      end

      opts.on("-t @LINE_ID", "Toggle status for line id") do |line_id|
        @mode = :toggle
        @message = line_id
      end

      opts.on("-D @LINE_ID", "Delete the specified line id") do |line_id|
        @mode = :delete
        @message = line_id
      end

      opts.on("-e", "--edit", "Open the file in $EDITOR for manual edits") do
        @mode = :edit
      end

      opts.on("-u", "--undo", "Undo the last change") do
        @mode = :undo
      end

      opts.on("-c", "--cleanup", "Sort items (todo items before done)") do
        @mode = :cleanup
      end

      opts.on("-P", "--purge", "Delete all done items") do
        @mode = :purge
      end

      opts.separator "Message:"
      opts.separator "    text @tag                        Records todo for @tag"
      opts.separator "    text @ID                         Records todo as child of parent ID"
      opts.separator "    @tag                             Displays todos for @tag"
    end
  end

  def validate_options
    # Set default file if not specified
    @file ||= File.expand_path("~/taf.md") unless @mode == :help

    @taf = Taf.new(@file) if @file
  end

  def execute_command
    case @mode
    when :help
      puts create_option_parser.help
    when :toggle
      toggle_command
    when :delete
      delete_command
    when :edit
      edit_command
    when :undo
      undo_command
    when :cleanup
      cleanup_command
    when :purge
      purge_command
    when :default
      default_command
    end
  end

  def toggle_command
    _text, _tag, line_id = TafHelper.parse_message(@message)
    unless line_id
      puts "Error: Invalid line ID format. Use @NUMBER (e.g., @21)".red
      exit 1
    end

    item = @taf.find_item_by_id(line_id)
    unless item
      puts "Error: Item with id #{line_id} not found".red
      exit 1
    end
    item_signatures = @taf.toggle(item)
    @taf = Taf.new(@file)
    system("clear")
    @taf.show_all(highlight_signatures: item_signatures)
  end

  def delete_command
    _text, _tag, line_id = TafHelper.parse_message(@message)
    unless line_id
      puts "Error: Invalid line ID format. Use @NUMBER (e.g., @21)".red
      exit 1
    end

    item = @taf.find_item_by_id(line_id)
    unless item
      puts "Error: Item with id #{line_id} not found".red
      exit 1
    end
    @taf.delete(item)
    @taf = Taf.new(@file)
    system("clear")
    @taf.show_all
  end

  def edit_command
    Taf.backup(@file)
    system("#{ENV['EDITOR'] || 'vim'} #{@file}")
    @taf = Taf.new(@file)
    system("clear")
    @taf.show_all
    puts "Taf file saved".green
  end

  def undo_command
    begin
      Taf.restore(@file)
      @taf = Taf.new(@file)
      system("clear")
      @taf.show_all
      puts "Undo successful".green
    rescue ArgumentError => e
      puts "Error: #{e.message}".red
      exit 1
    end
  end

  def cleanup_command
    @taf.cleanup
    @taf = Taf.new(@file)
    system("clear")
    @taf.show_all
    puts "Cleanup complete".green
  end

  def purge_command
    @taf.purge
    @taf = Taf.new(@file)
    system("clear")
    @taf.show_all
    puts "Purge complete".green
  end

  def default_command
    text, tag, parent_id = TafHelper.parse_message(@message)
    if tag.nil? && text.nil? && parent_id.nil?
      system("clear")
      @taf.show_all
    elsif text.nil?
      system("clear")
      @taf.show_tag(tag)
    else
      begin
        todo_signatures = @taf.add_todo(text, tag: tag, parent_id: parent_id)

        @taf = Taf.new(@file)
        system("clear")
        @taf.show_all(highlight_signatures: todo_signatures)
      rescue ArgumentError => e
        puts "Error: #{e.message}".red
        exit 1
      end
    end
  end
end
