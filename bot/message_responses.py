import asyncio
import json
import logging
import os
from urllib.parse import urlparse

import aiofiles
import emoji
import imagehash
from nio import DownloadError, DownloadResponse, crypto
from PIL import Image

import sqlite_functions as db
from chat_functions import send_reactions_to_message, send_text_to_room
from saucenao import get_image_source, get_source

logger = logging.getLogger(__name__)


class Message(object):

    def __init__(self, client, store, config, message_content, room, event):
        """Initialize a new Message

        Args:
            client (nio.AsyncClient): nio client used to interact with matrix

            store (Storage): Bot storage

            config (Config): Bot configuration parameters

            message_content (str): The body of the message

            room (nio.rooms.MatrixRoom): The room the event came from

            event (nio.events.room_events.RoomMessageText): The event defining the message
        """
        self.client = client
        self.store = store
        self.config = config
        self.message_content = message_content
        self.room = room
        self.event = event

    async def process(self):
        """Process and possibly respond to the message"""
        if self.message_content.lower() == "hello world":
            await self._hello_world()

    async def _hello_world(self):
        """Say hello"""
        text = "Hello, world!"
        await send_text_to_room(self.client, self.room.room_id, text)


class ProcessMedia(object):

    def __init__(self, client, store, config, room, event):
        self.client = client
        self.store = store
        self.config = config
        self.room = room
        self.event = event
        self.saucenao_token = config.saucenao_token

    async def process_media(self):
        #if self.event.sender != self.config.user_id:
        #    print(json.dumps(self.event.source, indent=4))

        database = self.room.room_id[1:].replace(":", "_")

        # If event is a reaction, store the vote
        try:
            if self.event.source[
                    "type"] == "m.reaction" and self.event.sender != self.config.user_id:
                reaction = emoji.demojize(
                    self.event.source["content"]["m.relates_to"]["key"])

                points = None
                if reaction == ":thumbs_up:":
                    points = 1
                elif reaction == ":OK_hand:":
                    points = 2
                elif reaction == ":red_heart:":
                    points = 3
                elif reaction == "Repost":
                    try:
                        parent_event_id = self.event.source["content"][
                            "m.relates_to"]["event_id"]
                        parent_event_info = await self.client.room_get_event(
                            self.room.room_id, parent_event_id)

                        # Fetch hash of event_id
                        event_id_hash = await db.fetch_one_hash(
                            parent_event_id, database)
                        hash_list_30 = await db.fetch_30d_hashes(database)
                        # Fetch all stored hashes
                        hash_list_all = await db.fetch_all_hashes(
                            parent_event_id, database)

                        event_id_dupe_list = []
                        dupes_30 = 0
                        dupes_all = 0

                        # Compare this event_id's hash with hashes from the past 30 days
                        for x in range(len(hash_list_30)):
                            # If the hash difference is less than 10, assume it is a duplicate
                            if (imagehash.hex_to_hash(
                                    event_id_hash[0])) - imagehash.hex_to_hash(
                                        hash_list_30[x][1]) < 10:
                                dupes_30 += 1
                                # Store duplicate photo event ids
                                event_id_dupe_list.append(
                                    str(hash_list_30[x][0]))
                        # Compare hash for message command was used on with all hashes
                        for x in range(len(hash_list_all)):
                            # If the hash difference is less than 10, assume it is a duplicate
                            if (imagehash.hex_to_hash(event_id_hash[0]) -
                                    imagehash.hex_to_hash(
                                        hash_list_all[x][1])) < 10:
                                dupes_all += 1
                                # Store duplicate photo message ids
                                #event_id_dupe_list.append(str(hash_list_all[x][0]))

                        # If duplicates were found, let the user know
                        if dupes_30 > 1:
                            text = f"That pic has been posted {dupes_30} times in the last 30 days"
                            if dupes_30 == dupes_all:
                                text += "."
                            else:
                                text += f", and {dupes_all} times total."

                            for x in range(len(event_id_dupe_list)):
                                # If this is the last dupe message_id, the ones before it
                                # have been deleted either by the user or an admin.
                                # Send a different message.
                                if x + 1 == len(event_id_dupe_list):
                                    text = f"That pic has been posted {dupes_30} times in the last 30 days"
                                    if dupes_30 != dupes_all:
                                        text += f" and {dupes_all} times total"
                                    text += ", but I couldn't find the other occurances. Maybe they were deleted?"

                                    await send_text_to_room(
                                        self.client, self.room.room_id, text)
                                else:
                                    await send_text_to_room(
                                        self.client, self.room.room_id, text,
                                        False, True, parent_event_id)
                                    # Reply to first occurance
                                    await send_text_to_room(
                                        self.client, self.room.room_id,
                                        "Here is the first occurance (if it hasn't been deleted).",
                                        False, True, event_id_dupe_list[x])
                                    break
                        print(f"dupes_30d: {dupes_30}")
                        return
                    except Exception as e:
                        print(f'Exception in Repost: {e}')

                elif reaction == "Source":
                    """
                    Need to figure out a way to get the associated URL to download the original image.
                    Can't just use event_id because that's the event_id for the reaction.
                    """
                    """
                    async def room_get_event(
                        self,
                        room_id: str,
                        event_id: str)
                    """

                    parent_event_id = self.event.source["content"][
                        "m.relates_to"]["event_id"]
                    parent_event_info = await self.client.room_get_event(
                        self.room.room_id, parent_event_id)

                    # See if it's E2EE
                    try:
                        if "key_ops" in str(parent_event_info.event.source):
                            encrypted_image = True
                            print(f"encrypted_image={encrypted_image}")
                        else:
                            encrypted_image = False
                            print(f"encrypted_image={encrypted_image}")
                    except Exception as e:
                        print(f"Exception while checking for E2EE key: {e}")

                    # See if there's a thumbnail URL
                    try:
                        thumbnail = None
                        if "thumbnail" in str(parent_event_info.event.source
                                              ) and thumbnail is None:
                            thumbnail = True
                            if encrypted_image is False:
                                image_url = parent_event_info.event.source[
                                    "content"]["info"]["thumbnail_url"]
                            elif encrypted_image is True:
                                image_url = parent_event_info.event.source[
                                    "content"]["info"]["thumbnail_file"]["url"]
                        else:
                            thumbnail = False
                            if encrypted_image is False:
                                image_url = parent_event_info.event.source[
                                    "content"]["url"]
                            elif encrypted_image is True:
                                image_url = parent_event_info.event.source[
                                    "content"]["file"]["url"]
                    except Exception as e:
                        print(
                            f"Exception while trying to assign file URL: {e}")
                    try:
                        parsed_url = urlparse(image_url)
                    except Exception as e:
                        print(
                            f"Exception while trying to assign E2EE thumbnail: {e}"
                        )

                    try:
                        # Download image data
                        media_data = await self.client.download(
                            parsed_url.netloc, parsed_url.path.strip("/"))
                        filename = parent_event_info.event.body

                        # Write image data to file
                        if encrypted_image is False:
                            async with aiofiles.open(f"./data/{filename}",
                                                     "wb") as f:
                                await f.write(media_data.body)
                        elif encrypted_image is True:
                            if thumbnail is True:
                                async with aiofiles.open(
                                        f"./data/{filename}", "wb") as f:
                                    await f.write(
                                        crypto.attachments.decrypt_attachment(
                                            media_data.body,
                                            parent_event_info.event.
                                            source["content"]["info"]
                                            ["thumbnail_file"]["key"]["k"],
                                            parent_event_info.event.
                                            source["content"]["info"]
                                            ["thumbnail_file"]["hashes"]
                                            ["sha256"],
                                            parent_event_info.event.
                                            source["content"]["info"]
                                            ["thumbnail_file"]["iv"],
                                        ))
                            else:
                                async with aiofiles.open(
                                        f"./data/{filename}", "wb") as f:
                                    await f.write(
                                        crypto.attachments.decrypt_attachment(
                                            media_data.body,
                                            parent_event_info.event.source[
                                                "content"]["file"]["key"]["k"],
                                            parent_event_info.event.
                                            source["content"]["file"]["hashes"]
                                            ["sha256"],
                                            parent_event_info.event.
                                            source["content"]["file"]["iv"],
                                        ))
                    except Exception as e:
                        print(f"Exception while downloading image data: {e}")
                    # Reply to message with source URL
                    await self.source(filename, parent_event_id)
                    return
                else:
                    print("Not a recognized emoji")

                if points is not None:
                    # Find original post's sender
                    og_sender = await db.find_sender(
                        database, self.event.source["content"]["m.relates_to"]
                        ["event_id"])

                    if og_sender is not None and og_sender != self.event.sender:
                        # Add reaction info to table (in case we need to retract points later)
                        await db.update_reaction_info(database,
                                                      self.event.event_id,
                                                      og_sender, points)
                        # Update media poster's points
                        await db.update_user_karma(database, og_sender, "+",
                                                   points)
        except Exception as e:
            print(f"Exception in storing reaction vote: {e}")
            pass

        # If event is a photo/video, send bot reactions
        try:
            msgtype = self.event.source["content"]["msgtype"]
            if msgtype == "m.video":
                await send_reactions_to_message(self.client, self.room.room_id,
                                                self.event.event_id, False,
                                                False)
            elif msgtype == "m.image":
                # See if it's E2EE
                try:
                    if "key_ops" in str(self.event.source):
                        encrypted_image = True
                        print(f"encrypted_image={encrypted_image}")
                    else:
                        encrypted_image = False
                        print(f"encrypted_image={encrypted_image}")
                except Exception as e:
                    print(f"Exception while checking for E2EE key: {e}")

                # See if there's a thumbnail URL
                try:
                    thumbnail = None
                    if "thumbnail" in str(
                            self.event.source) and thumbnail is None:
                        thumbnail = True
                        if encrypted_image is False:
                            image_url = self.event.source["content"]["info"][
                                "thumbnail_url"]
                        elif encrypted_image is True:
                            image_url = self.event.source["content"]["info"][
                                "thumbnail_file"]["url"]
                    else:
                        thumbnail = False
                        if encrypted_image is False:
                            image_url = self.event.source["content"]["url"]
                        elif encrypted_image is True:
                            image_url = self.event.source["content"]["file"][
                                "url"]
                except Exception as e:
                    print(f"Exception while trying to assign file URL: {e}")
                try:
                    parsed_url = urlparse(image_url)
                except Exception as e:
                    print(
                        f"Exception while trying to assign E2EE thumbnail: {e}"
                    )

                try:
                    # Download image data
                    media_data = await self.client.download(
                        parsed_url.netloc, parsed_url.path.strip("/"))
                    filename = self.event.body

                    # Write image data to file
                    if encrypted_image is False:
                        async with aiofiles.open(f"./data/{filename}",
                                                 "wb") as f:
                            await f.write(media_data.body)
                    elif encrypted_image is True:
                        if thumbnail is True:
                            async with aiofiles.open(f"./data/{filename}",
                                                     "wb") as f:
                                await f.write(
                                    crypto.attachments.decrypt_attachment(
                                        media_data.body,
                                        self.event.source["content"]["info"]
                                        ["thumbnail_file"]["key"]["k"],
                                        self.event.source["content"]["info"]
                                        ["thumbnail_file"]["hashes"]["sha256"],
                                        self.event.source["content"]["info"]
                                        ["thumbnail_file"]["iv"],
                                    ))
                        else:
                            async with aiofiles.open(f"./data/{filename}",
                                                     "wb") as f:
                                await f.write(
                                    crypto.attachments.decrypt_attachment(
                                        media_data.body,
                                        self.event.source["content"]["file"]
                                        ["key"]["k"],
                                        self.event.source["content"]["file"]
                                        ["hashes"]["sha256"],
                                        self.event.source["content"]["file"]
                                        ["iv"],
                                    ))
                except Exception as e:
                    print(f"Exception while downloading image data: {e}")
                # await add_to_queue(room.room_id, self.event.event_id)

                try:
                    reposted_bool = False

                    # Hash image
                    image_hash = imagehash.phash(
                        Image.open(f"./data/{filename}"))
                    print(str(image_hash))

                    # Delete image
                    os.remove(f"./data/{filename}")

                    print(f"event_id: {self.event.event_id[1:]}")

                    # Check if image is a repost within the last 30 days
                    hash_list_30 = await db.fetch_30d_hashes(database)
                    # Compare hash for message command was used on with hashes from past 30 days
                    event_id_dupe_list = []
                    dupes_30d = 0
                    for x in range(len(hash_list_30)):
                        # If the hash difference is less than 10, assume it is a duplicate
                        if (imagehash.hex_to_hash(str(image_hash)) -
                                imagehash.hex_to_hash(
                                    hash_list_30[x][1])) < 10:
                            dupes_30d += 1
                            # Store duplicate photo event ids
                            event_id_dupe_list.append(str(hash_list_30[x][0]))
                    print(f"dupes_30d: {dupes_30d}")
                    if dupes_30d > 0:
                        reposted_bool = True
                    else:
                        reposted_bool = False

                    # Store hash in db
                    await db.store_hash(database, self.event.event_id,
                                        str(image_hash))

                    # Store event_id and poster's username in message_karma table
                    await db.update_event_info(database, self.event.event_id,
                                               self.event.source["sender"])
                except Exception as e:
                    print(f"Exception while in hash process: {e}")

                # Send reactions. Attach source if room alias includes dtp
                # TODO: Make dtp a config option
                if True:  #"dtp" in self.room.canonical_alias:
                    await send_reactions_to_message(self.client,
                                                    self.room.room_id,
                                                    self.event.event_id,
                                                    reposted_bool, True)
                else:
                    await send_reactions_to_message(self.client,
                                                    self.room.room_id,
                                                    self.event.event_id,
                                                    reposted_bool, False)
        except KeyError:
            pass

        # If event is a redaction, see if we need to remove points
        try:
            if self.event.source["type"] == "m.room.redaction":
                result = await db.get_reaction_info(database,
                                                    self.event.redacts)

                # result might be None if user is deleting an image/message
                if result is not None:
                    # Subtract points that were redacted
                    await db.update_user_karma(database, result[0], "-",
                                               result[1])

                # Delete hash for message id if it's an image
                #await db.delete_hash(database, self.event.redacts)
        except Exception as e:
            print(f"Exception in redaction func: {e}")

    async def source(self, filename, event_id):
        # Send source URL
        try:
            text = get_source(filename, self.saucenao_token)
            await send_text_to_room(self.client, self.room.room_id, text,
                                    False, True, event_id)
        except Exception as e:
            print(f'Exception in source(): {e}')

        # Delete image
        os.remove(f"./data/{filename}")
        """
        # await add_to_queue(room.room_id, self.event.event_id)
        # If it's an mp4, convert it to gif
        if filename.endswith(".mp4"):
            convert_media(filename, TargetFormat.GIF)
            os.remove(filename)
            filename = "./media/source.gif"
        """
