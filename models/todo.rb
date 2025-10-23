require 'digest'

# Represents a single todo item in a tree structure
class Todo
  attr_accessor :idx, :status, :text, :children, :parent

  MIN_LENGTH = 3

  def initialize(status:, text:, idx: nil, children: [], parent: nil)
    @idx = idx
    @status = status
    @text = text
    @children = children
    @parent = parent
  end

  def done?
    @status == "done"
  end

  def todo?
    @status == "todo"
  end

  def signature
    Digest::MD5.hexdigest("#{text}|#{parent&.text}")
  end
end
