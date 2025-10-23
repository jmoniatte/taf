require_relative 'lib/taf/version'

Gem::Specification.new do |spec|
  spec.name          = "taf-cli"
  spec.version       = TAF_VERSION
  spec.authors       = ["Jean Moniatte"]
  spec.email         = ["jmoniatte@fastmail.com"]

  spec.summary       = "A simple CLI todo list manager"
  spec.description   = "Travail À Faire (taf) is a lightweight command-line tool that helps you manage your todos in a markdown file with support for tags and hierarchical organization."
  spec.homepage      = "https://github.com/jmoniatte/taf"
  spec.license       = "MIT"
  spec.required_ruby_version = ">= 2.6.0"

  spec.metadata["homepage_uri"] = spec.homepage
  spec.metadata["source_code_uri"] = "https://github.com/jmoniatte/taf"
  spec.metadata["changelog_uri"] = "https://github.com/jmoniatte/taf/blob/master/CHANGELOG.md"

  # Specify which files should be added to the gem when it is released.
  spec.files = Dir.glob("{bin,lib}/**/*") + %w[README.md LICENSE CHANGELOG.md]
  spec.bindir        = "bin"
  spec.executables   = ["taf"]
  spec.require_paths = ["lib"]

  spec.post_install_message = <<~MSG
    Thanks for installing taf-cli!

    Get started with:
      taf --help

    Your todos will be stored in ~/taf.md by default.

    For more info: https://github.com/jmoniatte/taf
  MSG

  # Dependencies
  # spec.add_dependency "example-gem", "~> 1.0"

  # Development dependencies
  spec.add_development_dependency "bundler", "~> 2.0"
  spec.add_development_dependency "rake", "~> 13.0"
end
