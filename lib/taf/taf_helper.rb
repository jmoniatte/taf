module TafHelper
  DEFAULT_TAG = "Untagged".freeze

  # Extracts text, tag, and parent_id from message
  # Returns [text, tag, parent_id]
  # - If @ID (numeric): parent_id is set, tag is nil
  # - If @tag (alphanumeric): tag is set, parent_id is nil
  # - Otherwise: both nil
  def self.parse_message(message)
    return [nil, nil, nil] if message.to_s.empty?

    if (tag_only = message[/^@[A-Za-z0-9][A-Za-z0-9_-]*$/])
      return parse_tag_or_parent(nil, tag_only)
    end

    tag = message[/ @[A-Za-z0-9][A-Za-z0-9_-]*$/]
    if tag
      text = message.sub(/ @[A-Za-z0-9][A-Za-z0-9_-]*$/, "")
      text.strip!
      parse_tag_or_parent(text, tag)
    else
      text = message.strip
      [text, nil, nil]
    end
  end

  # Determines if tag_string is a parent ID or a tag
  def self.parse_tag_or_parent(text, tag_string)
    cleaned = tag_string.strip.delete_prefix("@")

    if cleaned.match?(/^\d+$/)
      [text, nil, cleaned.to_i]
    else
      [text, tag_name(tag_string), nil]
    end
  end

  # Transforms `@tag-name` to `Tag Name`
  def self.tag_name(tag)
    tag
      .strip
      .delete_prefix("@")
      .split(/[-_]/)
      .map(&:capitalize)
      .join(" ")
  end
end
