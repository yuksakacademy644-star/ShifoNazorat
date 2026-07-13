import re

def normalize_phone(phone_str: str) -> str:
    """
    Normalizes a phone number to only digits and keeps the last 9 digits.
    For Uzbek numbers, this helps match e.g. +998901234567, 998901234567, 90 123 45 67
    all to '901234567'.
    """
    if not phone_str:
        return ""
    # Remove all non-digit characters
    digits = re.sub(r'\D', '', phone_str)
    # If the number is at least 9 digits, take the last 9 digits
    if len(digits) >= 9:
        return digits[-9:]
    return digits

if __name__ == '__main__':
    import bot
    print("Starting ShifoNazorat Bot...")
    bot.main()

