from textual.widgets import Button


def flat_button(label: str, id: str, classes: str = "") -> Button:
    button = Button(label, id=id, classes=classes)
    # A click must not take focus off the view, which keeps it for its keys
    button.can_focus = False
    return button
