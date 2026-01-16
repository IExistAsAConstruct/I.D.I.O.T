#region Imports
import hikari
import lightbulb

import io
import aiohttp
from database import bot_messages
from PIL import Image, ImageDraw, ImageFont, ImageSequence
from datetime import datetime, timezone
#endregion

#region Loader and Group
loader = lightbulb.Loader()
meme = lightbulb.Group("meme", "Joke commands")
#endregion

#region Text Functions
def wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """
    Wrap text to fit within a max width.

    Args:
        text (str): The text to wrap.
        font (ImageFont.FreeTypeFont): The font used to measure text size.
        max_width (int): The maximum width in pixels.

    Returns:
        list[str]: A list of wrapped text lines.
    """
    words = text.split()
    lines = []
    current_line = []

    for word in words:
        test_line = " ".join(current_line + [word])
        bbox = font.getbbox(test_line)
        line_width = bbox[2] - bbox[0]

        if line_width <= max_width:
            current_line.append(word)
        else:
            if current_line:
                lines.append(" ".join(current_line))
                current_line = [word]
            else:
                lines.append(word)

    if current_line:
        lines.append(" ".join(current_line))

    return lines

def draw_text_with_outline(
        draw: ImageDraw.ImageDraw,
        position: tuple[int, int],
        text: str,
        font: ImageFont.FreeTypeFont,
        outline_width: int = 2,
) -> None:
    """
    Draw text with an outline on an image.

    Args:
        draw (ImageDraw.ImageDraw): The drawing context.
        position (tuple[int, int]): The (x, y) position to draw the text.
        text (str): The text to draw.
        font (ImageFont.FreeTypeFont): The font used for the text.
        outline_width (int): The width of the outline.
    """
    x, y = position

    # Draw outline
    for dx in range(-outline_width, outline_width + 1):
        for dy in range(-outline_width, outline_width + 1):
            if dx != 0 or dy != 0:
                draw.text(
                    (x + dx, y + dy),
                    text,
                    font=font,
                    fill="black"
                )

    # Draw main text
    draw.text(position, text, font=font, fill="white")

def add_text_to_frame(
        frame: Image.Image,
        top_text: str,
        bottom_text: str,
        font: ImageFont.FreeTypeFont
) -> Image.Image:
    """
    Add top and bottom text to a single image frame.

    Args:
        frame (Image.Image): The image frame.
        top_text (str): The text to place at the top of the image.
        bottom_text (str): The text to place at the bottom of the image.
        font (ImageFont.FreeTypeFont): The font used for the text.

    Returns:
        Image.Image: The image frame with text added.
    """

    if frame.mode == 'P':
        frame = frame.convert('RGBA')
    elif frame.mode != 'RGB' and frame.mode != 'RGBA':
        frame = frame.convert('RGB')

    width, height = frame.size
    draw = ImageDraw.ImageDraw(frame)

    aspect_ratio = width / height

    if aspect_ratio > 2.0:
        # Wide image, use smaller margin
        margin = int(height * 0.05)
    elif aspect_ratio < 0.5:
        # Tall image, use larger margin
        margin = int(height * 0.08)
    else:
        margin = int(min(width, height) * 0.05)

    max_text_width = width - (2 * margin)

    if top_text:
        top_text_upper = top_text.upper()
        top_lines = wrap_text(top_text_upper, font, max_text_width)

        y_offset = margin
        for line in top_lines:
            bbox = font.getbbox(line)
            line_width = bbox[2] - bbox[0]
            line_height = bbox[3] - bbox[1]

            x_offset = (width - line_width) // 2

            draw_text_with_outline(
                draw,
                (x_offset, y_offset),
                line,
                font,
                outline_width=3
            )

            y_offset += line_height + 5

    if bottom_text:
        bottom_text_upper = bottom_text.upper()
        bottom_lines = wrap_text(bottom_text_upper, font, max_text_width)

        total_height = 0
        for line in bottom_lines:
            bbox = font.getbbox(line)
            line_height = bbox[3] - bbox[1]
            total_height += line_height + 5

        y_offset = height - total_height - margin

        for line in bottom_lines:
            bbox = font.getbbox(line)
            line_width = bbox[2] - bbox[0]
            line_height = bbox[3] - bbox[1]

            x_offset = (width - line_width) // 2

            draw_text_with_outline(
                draw,
                (x_offset, y_offset),
                line,
                font,
                outline_width=3
            )

            y_offset += line_height + 5

    return frame

def get_font(width: int, height: int) -> ImageFont.FreeTypeFont:
    """
    Get an appropriate font based on image height.

    Args:
        height (int): The height of the image.

    Returns:
        ImageFont.FreeTypeFont: The loaded font.
    """

    base_size = min(width, height)

    aspect_ratio = width / height

    if aspect_ratio > 2.0:
        font_size = int(height / 15)
    elif aspect_ratio < 0.5:
        font_size = int(height / 8)
    else:
        font_size = int(height / 10)

    font_size = max(20, min(font_size, 100))

    font_paths = [
        "impact.ttf",
        "/usr/share/fonts/truetype/msttcorefonts/impact.ttf",
        "/System/Library/Fonts/Supplemental/Impact.ttf", # macOS
        "C:\\Windows\\Fonts\\impact.ttf", # Windows
        "arial.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
    ]

    for font_path in font_paths:
        try:
            return ImageFont.truetype(font_path, font_size)
        except OSError:
            continue

    return ImageFont.load_default()

#endregion

#region Image Functions

async def download_image(url: str) -> bytes:
    """
    Download an image from a URL.

    Args:
        url (str): The URL of the image.

    Returns:
        bytes: The image data.
    """
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status != 200:
                raise ValueError(f"Failed to download image: {response.status}")
            return await response.read()

#endregion

#region Meme Creation

def create_meme(
        image_data: bytes,
        top_text: str = "",
        bottom_text: str = ""
) -> tuple[io.BytesIO, str]:
    """
    Create a meme image with top and bottom text.

    Args:
        image_data (bytes): The image data.
        top_text (str): The text to place at the top of the image.
        bottom_text (str): The text to place at the bottom of the image.

    Returns:
        tuple[io.BytesIO, str]: The generated meme as a BytesIO object and the format ('PNG' or 'GIF').
    """

    image = Image.open(io.BytesIO(image_data))

    width, height = image.size
    font = get_font(width, height)

    is_animated = getattr(image, "is_animated", False)

    if is_animated:
        frames = []
        durations = []

        for frame in ImageSequence.Iterator(image):
            duration = frame.info.get('duration', 100)
            durations.append(duration)

            processed_frame = add_text_to_frame(
                frame.copy(),
                top_text,
                bottom_text,
                font
            )

            processed_frame = processed_frame.convert('RGB').convert('P', palette=Image.ADAPTIVE)
            frames.append(processed_frame)

        output_buffer = io.BytesIO()
        frames[0].save(
            output_buffer,
            format="GIF",
            save_all=True,
            append_images=frames[1:],
            duration=durations,
            loop=0,
            optimize=True
        )
        output_buffer.seek(0)

        return output_buffer, "GIF"
    else:
        processed_image = add_text_to_frame(
            image,
            top_text,
            bottom_text,
            font
        )

        output_buffer = io.BytesIO()

        if processed_image.mode == 'RGBA':
            processed_image.save(output_buffer, format="PNG")
        else:
            processed_image.convert('RGB').save(output_buffer, format="PNG")

        output_buffer.seek(0)

        return output_buffer, "PNG"

@meme.register()
class MakeMeme(
    lightbulb.SlashCommand,
    name="make",
    description="Create a meme with top and bottom text."
):
    top_text = lightbulb.string("top_text", "Text to place at the top of the image", default="")
    bottom_text = lightbulb.string("bottom_text", "Text to place at the bottom of the image", default="")
    image = lightbulb.attachment("image", "The base image to use.", default=None)
    image_url = lightbulb.string("image_url", "URL of the image to use for the meme", default=None)

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        """
        Create a meme with the provided top and bottom text on the given image. Works with both static and animated images.
        """
        await ctx.defer()

        top = self.top_text
        bottom = self.bottom_text

        if not top and not bottom:
            await ctx.respond("You must provide at least top text or bottom text for the meme.")
            return

        image_data = None

        try:
            if self.image:
                image_data = await self.image.read()
            elif self.image_url:
                image_data = await download_image(self.image_url)
            else:
                await ctx.respond("You must provide either an image attachment or an image URL.")
                return

            output, format_type = create_meme(image_data, top, bottom)

            file_extension = 'gif' if format_type == 'GIF' else 'png'

            response = await ctx.respond(
                attachment=hikari.Bytes(output, f"meme.{file_extension}")
            )

            message = await ctx.client.app.rest.fetch_message(ctx.channel_id, response)

            bot_messages.insert_one({
                "message_id": str(message.id),
                "channel_id": str(ctx.channel_id),
                "guild_id": str(ctx.guild_id),
                "creator_id": str(ctx.user.id),
                "type": "meme",
                "created_at": datetime.now(timezone.utc).isoformat()
            })

            print(f"Meme created by user {ctx.user.id} in guild {ctx.guild_id}, message ID: {message.id}")

        except ValueError as e:
            await ctx.respond(f"An error occurred while creating the meme: {str(e)}")
        except Exception as e:
            await ctx.respond(f"An unexpected error occurred: {str(e)}")
            print(f"Error creating meme: {str(e)}")

#endregion

loader.command(meme)