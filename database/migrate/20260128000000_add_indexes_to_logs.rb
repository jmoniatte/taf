Sequel.migration do
  change do
    alter_table :logs do
      add_index :logged_at
      add_index :action
      add_index :context
    end
  end
end
