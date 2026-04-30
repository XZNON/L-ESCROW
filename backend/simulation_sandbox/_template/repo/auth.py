ADMIN_PASSWORD = "ADMIN_1234"  # BUG: hardcoded credential


def check_admin(password):
    return password == ADMIN_PASSWORD
