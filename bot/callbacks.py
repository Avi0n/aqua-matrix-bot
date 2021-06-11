from chat_functions import send_text_to_room, send_reactions_to_message
from bot_commands import Command
from nio import JoinError, DownloadResponse, DownloadError, crypto
from message_responses import Message
import sqlite_functions as db

from urllib.parse import urlparse
import aiofiles
import asyncio
import imagehash
from PIL import Image
import emoji
import os
import json
import logging

logger = logging.getLogger(__name__)


class Callbacks(object):
    def __init__(self, client, store, config):
        """
        Args:
            client (nio.AsyncClient): nio client used to interact with matrix

            store (Storage): Bot storage

            config (Config): Bot configuration parameters
        """
        self.client = client
        self.store = store
        self.config = config
        self.command_prefix = config.command_prefix

    # Print json to console
    async def process_event(self, room, event):
        if event.sender != self.config.user_id:
            print(json.dumps(event.source, indent=4))
        #print(room.room_id)
        #print(json.dumps(room.source, indent=4))
        """
        New workflow will be:
        1) If m.image, store event_id in a db with columns 'room_id, event_id, reacted_to, hashed'
        2) send_reactions_to_message will send 3 emoji reactions marking reacted_to as T when complete
        3) Function to run through all event_ids, fetch URL, download media, hash it, store hash, then delete media from disk
        4) Function to run through all event_ids, compare hash to all previous hashes, and react with "Repost (DATE)" if repost
        4) Function to delete all db records WHERE 'reacted_to and hashed are TRUE'
        """

        database = room.room_id[1:].replace(":", "_")

        # If event is a reaction, store the vote
        try:
            if event.source[
                    "type"] == "m.reaction" and event.sender != self.config.user_id:
                reaction = emoji.demojize(
                    event.source["content"]["m.relates_to"]["key"])

                points = None
                if reaction == ":thumbs_up:":
                    points = 1
                elif reaction == ":OK_hand:":
                    points = 2
                elif reaction == ":red_heart:":
                    points = 3
                else:
                    print("Not a recognized emoji")

                if points is not None:
                    # Find original post's sender
                    og_sender = await db.find_sender(
                        database,
                        event.source["content"]["m.relates_to"]["event_id"])

                    if og_sender is not None and og_sender != event.sender:
                        # Add reaction info to table (in case we need to retract points later)
                        await db.update_reaction_info(database, event.event_id,
                                                      og_sender, points)
                        # Update media poster's points
                        await db.update_user_karma(database, og_sender, "+",
                                                   points)
        except Exception as e:
            print(f"Exception in storing reaction vote: {e}")
            pass

        # If event is a photo/video, send bot reactions
        try:
            msgtype = event.source["content"]["msgtype"]
            if msgtype == "m.video":
                await send_reactions_to_message(self.client, room.room_id,
                                                event.event_id, False)
            elif msgtype == "m.image":
                # See if it's E2EE
                try:
                    if "key_ops" in str(event.source):
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
                    if "thumbnail" in str(event.source) and thumbnail is None:
                        thumbnail = True
                        if encrypted_image is False:
                            image_url = event.source["content"]["info"][
                                "thumbnail_url"]
                        elif encrypted_image is True:
                            image_url = event.source["content"]["info"][
                                "thumbnail_file"]["url"]
                    else:
                        thumbnail = False
                        if encrypted_image is False:
                            image_url = event.source["content"]["url"]
                        elif encrypted_image is True:
                            image_url = event.source["content"]["file"]["url"]
                except Exception as e:
                    print(f"Exception while trying to assign file URL: {e}")
                try:
                    parsed_url = urlparse(image_url)
                    print(f"parsed_url: {parsed_url}")
                except Exception as e:
                    print(
                        f"Exception while trying to assign E2EE thumbnail: {e}"
                    )

                try:
                    # Download image data
                    media_data = await self.client.download(
                        parsed_url.netloc, parsed_url.path.strip("/"))
                    filename = event.body

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
                                        event.source["content"]["info"]
                                        ["thumbnail_file"]["key"]["k"],
                                        event.source["content"]["info"]
                                        ["thumbnail_file"]["hashes"]["sha256"],
                                        event.source["content"]["info"]
                                        ["thumbnail_file"]["iv"],
                                    ))
                        else:
                            async with aiofiles.open(f"./data/{filename}",
                                                     "wb") as f:
                                await f.write(
                                    crypto.attachments.decrypt_attachment(
                                        media_data.body,
                                        event.source["content"]["file"]["key"]
                                        ["k"],
                                        event.source["content"]["file"]
                                        ["hashes"]["sha256"],
                                        event.source["content"]["file"]["iv"],
                                    ))
                except Exception as e:
                    print(f"Exception while downloading image data: {e}")
                # await add_to_queue(room.room_id, event.event_id)

                try:
                    reposted_bool = False

                    # Hash image
                    image_hash = imagehash.phash(
                        Image.open(f"./data/{filename}"))
                    print(str(image_hash))

                    # Delete image
                    os.remove(f"./data/{filename}")

                    print(f"event_id: {event.event_id[1:]}")

                    # Check if image is a repost within the last 30 days
                    hash_list_30 = await db.fetch_30d_hashes(database)
                    # Compare hash for message command was used on with hashes from past 30 days
                    message_id_dupe_list = []
                    dupes_30d = 0
                    for x in range(len(hash_list_30)):
                        # If the hash difference is less than 10, assume it is a duplicate
                        if (imagehash.hex_to_hash(str(image_hash)) -
                                imagehash.hex_to_hash(
                                    hash_list_30[x][1])) < 10:
                            dupes_30d += 1
                            # Store duplicate photo event ids
                            message_id_dupe_list.append(str(
                                hash_list_30[x][0]))
                    print(f"dupes_30d: {dupes_30d}")
                    if dupes_30d > 0:
                        reposted_bool = True
                    else:
                        reposted_bool = False

                    # Store hash in db
                    await db.store_hash(database, event.event_id,
                                        str(image_hash))

                    # Store event_id and poster's username in message_karma table
                    await db.update_event_info(database, event.event_id,
                                               event.source["sender"])
                except Exception as e:
                    print(f"Exception while in hash process: {e}")
                # Send reactions
                await send_reactions_to_message(self.client, room.room_id,
                                                event.event_id, reposted_bool)
        except KeyError:
            pass

        # If event is a redaction, see if we need to remove points
        try:
            if event.source["type"] == "m.room.redaction":
                result = await db.get_reaction_info(database, event.redacts)
                print(f"result: {result}")
                # result might be None if user is deleting an image/message
                if result is not None:
                    # Subtract points that were redacted
                    await db.update_user_karma(database, result[0], "-",
                                               result[1])
                    text = (f"{result[1]} subtracted from {result[0]}")
                    await send_text_to_room(self.client, room.room_id, text)

                # Delete hash for message id if it's an image
                await db.delete_hash(database, event.redacts)
        except Exception as e:
            print(f"Exception in redaction func: {e}")

    async def message(self, room, event):
        """Callback for when a message event is received

        Args:
            room (nio.rooms.MatrixRoom): The room the event came from

            event (nio.events.room_events.RoomMessageText): The event 
            defining the message

        """
        # Extract the message text
        msg = event.body

        # Ignore messages from ourselves
        if event.sender == self.client.user:
            return

        logger.debug(f"Bot message received for room {room.display_name} | "
                     f"{room.user_name(event.sender)}: {msg}")

        # Process as message if in a public room without command prefix
        has_command_prefix = msg.startswith(self.command_prefix)
        if not has_command_prefix and not room.is_group:
            # General message listener
            message = Message(self.client, self.store, self.config, msg, room,
                              event)
            await message.process()
            return

        # Otherwise if this is in a 1-1 with the bot or features a command prefix,
        # treat it as a command
        if has_command_prefix:
            # Remove the command prefix
            msg = msg[len(self.command_prefix):]

        command = Command(self.client, self.store, self.config, msg, room,
                          event)
        await command.process()

    async def invite(self, room, event):
        """Callback for when an invite is received. Join the room specified in 
        the invite"""
        logger.debug(f"Got invite to {room.room_id} from {event.sender}.")

        # Attempt to join 3 times before giving up
        for attempt in range(3):
            result = await self.client.join(room.room_id)
            if type(result) == JoinError:
                logger.error(
                    f"Error joining room {room.room_id} (attempt %d): %s",
                    attempt,
                    result.message,
                )
            else:
                break
        else:
            logger.error("Unable to join room: %s", room.room_id)

        # Successfully joined room
        logger.info(f"Joined {room.room_id}")
