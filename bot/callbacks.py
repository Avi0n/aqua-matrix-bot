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
        print(json.dumps(event.source, indent=4))
        #print(room.room_id)
        #print(json.dumps(room.source, indent=4))
        """
        Example event.source:
        {'type': 'm.room.message', 'sender': '@avion:pcg.life', 'content': {'body': 'image.png', 'info': {'size': 7583817, 'mimetype': 'image/png', 'thumbnail_info': {'w': 320, 'h': 600, 'mimetype': 'image/png', 'size': 275042}, 'w': 2189, 'h': 4096, 'thumbnail_url': 'mxc://pcg.life/04aab12c312b3293f961b5b9b28974611a612ff9'}, 'msgtype': 'm.image', 'url': 'mxc://pcg.life/0a98492dbe197a234e987778288ada09ed6a63ca'}, 'origin_server_ts': 1619648554322, 'unsigned': {'age': 68}, 'event_id': '$JBfRDkYvMmM-KTEh26CgMVchzwpDQo5vJCr3908N1J4'}
        """
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
            if event.source["type"] == "m.reaction" and event.sender != self.config.user_id:
                reaction = emoji.demojize(event.source["content"]["m.relates_to"]["key"])

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
                    og_sender = await db.find_sender(database, event.source["content"]["m.relates_to"]["event_id"])

                    if og_sender is not None:                    
                        # Add reaction info to table (in case we need to retract points later)
                        await db.update_reaction_info(database, event.event_id, event.sender, points)
                        # Update media poster's points
                        await db.update_user_karma(database, og_sender, "+", points)
        except Exception as e:
            print(f"Exception in storing reaction vote: {e}")
            pass

        # If event is a redaction, see if we need to remove points
        try:
            if event.source["type"] == "m.room.redaction":
                result = await db.get_reaction_info(database, event.redacts)
                
                # Subtract points that were redacted
                await db.update_user_karma(database, result[0], "-", result[1])
        except Exception as e:
            print(f"Exception in redaction func: {e}")
        # If event is a photo/video, send bot reactions
        try:
            msgtype = event.source["content"]["msgtype"]
            if msgtype == "m.video":
                await send_reactions_to_message(self.client, room.room_id,
                                                event.event_id, False)
            elif msgtype == "m.image":
                # Check if it's encrypted
                try:
                    thumb_url = event.source["content"]["info"][
                        "thumbnail_url"]
                    encrypted_image = False
                except Exception as e:
                    print(str(e))
                    try:
                        thumb_url = event.source["content"]["info"][
                            "thumbnail_file"]["url"]
                        encrypted_image = True
                    except Exception as e:
                        print(str(e))

                parsed_url = urlparse(thumb_url)

                try:
                    # Download image data
                    media_data = await self.client.download(
                        parsed_url.netloc, parsed_url.path.strip("/"))
                    filename = event.body

                    # Write image data to file
                    print(f"is encrypted: {encrypted_image}")
                    if encrypted_image is False:
                        async with aiofiles.open(f"./data/{filename}",
                                                 "wb") as f:
                            await f.write(media_data.body)
                    elif encrypted_image is True:
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
                except Exception as e:
                    print(f"Exception while downloading image data: {e}")
                # await add_to_queue(room.room_id, event.event_id)                

                # Hash image
                image_hash = imagehash.phash(Image.open(f"./data/{filename}"))
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
                            imagehash.hex_to_hash(hash_list_30[x][1])) < 10:
                        dupes_30d += 1
                        # Store duplicate photo event ids
                        message_id_dupe_list.append(str(hash_list_30[x][0]))
                print(f"dupes_30d: {dupes_30d}")
                if dupes_30d > 0:
                    reposted_bool = True
                else:
                    reposted_bool = False

                # Store hash in db
                await db.store_hash(database, event.event_id, str(image_hash))

                # Store event_id and poster's username in message_karma table
                await db.update_event_info(database, event.event_id, event.source["sender"])

                # Send reactions
                await send_reactions_to_message(self.client, room.room_id,
                                                event.event_id, reposted_bool)
        except KeyError:
            pass

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
