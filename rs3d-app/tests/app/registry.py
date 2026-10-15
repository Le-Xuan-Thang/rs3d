"""Lets a test reach objects that a NiceGUI simulation page creates (the page runs in the same process)."""

REG: dict = {}


class NoKeyring:
    def get_password(self, *a):
        return None

    def set_password(self, *a):
        pass

    def delete_password(self, *a):
        pass
