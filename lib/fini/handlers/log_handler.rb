require_relative '../presenters/log/terminal_presenter'
require_relative '../presenters/log/markdown_presenter'
require_relative '../parsers/log/markdown_parser'

module Fini
  class LogHandler
    # Creates a log from a message string
    # Example: "Worked on task @2h @backend"
    def self.create(message)
      log = Log.create_from_message(message)
      view_days(log.logged_at.to_date)
      log
    end

    def self.view_days(start_date, end_date = nil)
      end_date ||= start_date
      start_date, end_date = end_date, start_date if start_date < end_date

      range = (end_date.to_time)..(start_date.to_time + (24 * 60 * 60) - 1)
      logs = Log.where(logged_at: range).order(:logged_at).all

      Presenters::Log::TerminalPresenter.render(logs)
    end

    def self.edit_days(start_date, end_date = nil)
      require 'tempfile'

      end_date ||= start_date
      start_date, end_date = end_date, start_date if start_date < end_date

      # Fetch logs for the date range
      range = (end_date.to_time)..(start_date.to_time + (24 * 60 * 60) - 1)
      logs = Log.where(logged_at: range).order(:logged_at).all

      # Generate markdown content
      tempfile = Tempfile.new(['fini-edit-', '.md'])
      tempfile.write(Presenters::Log::MarkdownPresenter.render(logs))
      tempfile.close

      # Open in editor
      editor = ENV['EDITOR'] || 'vim'
      system("#{editor} #{tempfile.path}")

      # Parse edited content
      content = File.read(tempfile.path)
      parsed = Parsers::Log::MarkdownParser.parse(content)

      return if parsed[:dates].empty?

      # Delete logs for dates that were in the file
      parsed[:dates].each do |file_date|
        # Delete all database records for that day
        date = Date.parse(file_date)
        range = date.to_time...(date.to_time + (24 * 60 * 60))
        Log.where(logged_at: range).delete
      end

      # Create new logs from edited content
      parsed[:entries].each do |entry|
        Log.create_from_message(entry[:message], entry[:logged_at])
      end

      tempfile.unlink

      # Show updated logs for the date range
      view_days(start_date, end_date)
      if start_date == end_date
        puts "✓ Logs updated for #{start_date}".green
      else
        puts "✓ Logs updated for #{end_date} to #{start_date}".green
      end
    end

    def self.reprocess
      Log.each(&:reprocess)
    end
  end
end
