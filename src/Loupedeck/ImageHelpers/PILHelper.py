import io

# Displays
DISPLAYS = {
    "center": { "id": bytes('\x00A'.encode("ascii")), "width": 360, "height": 270 }, # "A"
    "left":   { "id": bytes('\x00L'.encode("ascii")), "width": 60,  "height": 270 }, # "L"
    "right":  { "id": bytes('\x00R'.encode("ascii")), "width": 60,  "height": 270 }, # "R"
}

def get_dimensions(display):
    width = 90
    height = 90
    if type(display) != str:
        print(f"PILHelper::get_dimensions: invalid deck '{display}', assuming button size")
        return (width, height)
    if display in DISPLAYS.keys():
        width = DISPLAYS[display]["width"]
        height = DISPLAYS[display]["height"]
    elif display == "full":
        width = DISPLAYS["left"]["width"] + DISPLAYS["center"]["width"] + DISPLAYS["right"]["width"]
        height = DISPLAYS["left"]["height"] + DISPLAYS["center"]["height"] + DISPLAYS["right"]["height"]
    elif display != "button":
        print(f"PILHelper::get_dimensions: invalid deck '{display}', assuming button size")
    return (width, height)


def create_image(deck, background='black', display="button"):
    """
    Creates a new PIL Image with the correct image dimensions for the given
    StreamDeck device's keys.

    .. seealso:: See :func:`~PILHelper.to_native_format` method for converting a
                 PIL image instance to the native image format of a given
                 StreamDeck device.

    :param Loupedeck deck: Loupedeck device.
    :param str background: Background color to use, compatible with `PIL.Image.new()`.
    :param str display: button name to generate a compatible image for.

    :rtype: PIL.Image
    :return: Created PIL image
    """
    from PIL import Image

    return Image.new("RGB", get_dimensions(display=display), background)


def create_scaled_image(deck, image, margins=[0, 0, 0, 0], background='black', display="button"):
    """
    Creates a new key image that contains a scaled version of a given image,
    resized to best fit the given StreamDeck device's keys with the given
    margins around each side.

    The scaled image is centered within the new key image, offset by the given
    margins. The aspect ratio of the image is preserved.

    .. seealso:: See :func:`~PILHelper.to_native_format` method for converting a
                 PIL image instance to the native image format of a given
                 StreamDeck device.

    :param Loupedeck deck: Loupedeck device.
    :param Image image: PIL Image object to scale
    :param str background: Background color to use, compatible with `PIL.Image.new()`.
    :param str display: button name to generate a compatible image for.

    :rtrype: PIL.Image
    :return: Loaded PIL image scaled and centered
    """
    from PIL import Image

    if len(margins) != 4:
        raise ValueError("Margins should be given as an array of four integers.")

    final_image = create_image(deck, background=background, display=display)

    thumbnail_max_width = final_image.width - (margins[1] + margins[3])
    thumbnail_max_height = final_image.height - (margins[0] + margins[2])

    thumbnail = image.convert("RGBA")
    thumbnail.thumbnail((thumbnail_max_width, thumbnail_max_height), Image.LANCZOS)

    thumbnail_x = (margins[3] + (thumbnail_max_width - thumbnail.width) // 2)
    thumbnail_y = (margins[0] + (thumbnail_max_height - thumbnail.height) // 2)

    final_image.paste(thumbnail, (thumbnail_x, thumbnail_y), thumbnail)

    return final_image


def to_native_format(deck, image):
    """
    Converts a given PIL image to the native image format for a LoudeckLive,
    suitable for passing to :func:`~send_buffer`.
    Loupedeck uses 16-bit (5-6-5) LE RGB colors
    """
    def rgb565(r, g, b, a=255):
        p1 = r & 248  # 11111000
        p1d = p1 >> 3    # display

        p2a = g & 224 # 11100000
        p2a = p2a >> 5
        p2b = g & 28  # 00011100
        p2b = p2b << 3
        p2bd = p2b >> 5  # display

        p3 = b & 248
        p3 = p3 >> 3

        b1 = p1 + p2a
        b2 = p2b + p3
        b = b1 * 256 + b2
        # if i == j:
        #     print(f"{i},{j}: ({r}={r:08b}, {g}={g:08b}, {b}={b:08b}) => ({p1d:05b}|{p2a:03b}|{p2bd:03b}|{p3:05b}) => ({b1:08b}{b2:08b}) = {b:016b}")
        return b

    buff = bytearray()
    for j in range(image.height):
        for i in range(image.width):
            p = image.getpixel((i, j))
            b16 = rgb565(*p)
            buff = buff + b16.to_bytes(2, "little") # little?? really
    return buff
