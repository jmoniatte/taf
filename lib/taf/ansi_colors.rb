module AnsiColors
  ANSI_RESET = "\u001B[0m".freeze
  ANSI_BLACK = "\u001B[30m".freeze
  ANSI_RED = "\u001B[31m".freeze
  ANSI_GREEN = "\u001B[32m".freeze
  ANSI_YELLOW = "\u001B[33m".freeze
  ANSI_BLUE = "\u001B[34m".freeze
  ANSI_PURPLE = "\u001B[35m".freeze
  ANSI_CYAN = "\u001B[36m".freeze
  ANSI_WHITE = "\u001B[97m".freeze
  ANSI_GREY = "\u001B[37m".freeze
  ANSI_HIGHLIGHT = "\u001B[43;30m".freeze
  ANSI_DEFAULT = "\u001B[39m".freeze
end

class String
  AnsiColors.constants.each do |const_name|
    next if const_name == :ANSI_RESET

    color_name = const_name.to_s.sub(/^ANSI_/, '').downcase
    color_code = AnsiColors.const_get(const_name)

    define_method(color_name) do
      "#{color_code}#{self}#{AnsiColors::ANSI_RESET}"
    end
  end
end
