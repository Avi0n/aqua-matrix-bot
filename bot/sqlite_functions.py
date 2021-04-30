import os
import sqlite3

import aiosqlite
from emoji import emojize


# Check if all databases exist
def check_dbs_exist():
    table_list = ["user_room_ids", "group_members", "bot_queue"]
    for x in range(len(table_list)):
        try:
            db = sqlite3.connect(f"db/{table_list[x]}.db")
            sql = f"SELECT * FROM {table_list[x]};"
            cursor = db.cursor()

            # Execute the SQL command
            cursor.execute(sql)
            # Fetch all the rows in a list of lists.
            result = cursor.fetchall()

            cursor.close()
            db.close()
        except Exception as e:
            if "no such table" in str(e):
                print(f"{table_list[x]} is missing. Creating.")
                # Populate db with missing table
                db = sqlite3.connect(f"db/{table_list[x]}.db")
                cursor = db.cursor()

                # Create table
                if table_list[x] == "bot_queue":
                    sql = f'''
                           CREATE TABLE {table_list[x]} (
                           room_id TEXT NOT NULL,
                           event_id TEXT NOT NULL,
                           reacted_to INTEGER DEFAULT 0,
                           hashed INTEGER DEFAULT 0)
                           '''
                else:
                    sql = f'''
                            CREATE TABLE {table_list[x]} (
                            room_id TEXT DEFAULT NULL,
                            username TEXT DEFAULT NULL )
                            '''
                try:
                    # Execute the SQL command
                    cursor.execute(sql)
                except Exception as e:
                    print(
                        "Error in check_first_db_run while creating the table"
                        + f" {table_list[x]}: {e}")
                cursor.close()
                db.close()

    print("Done checking database tables, starting the bot.")
    return


def populate_db(database):
    print("Entered populate_db")
    populated_status = False
    table_list = ["message_karma", "user_karma", "media_hash", "media_tags"]

    for x in range(len(table_list)):
        try:
            db = sqlite3.connect("db/" + database + ".db")
            sql = f"SELECT * FROM {table_list[x]};"
            cursor = db.cursor()

            # Execute the SQL command
            cursor.execute(sql)
            # Fetch all the rows in a list of lists.
            result = cursor.fetchall()

            populated_status = True
        except:
            if table_list[x] == "message_karma":
                sql = '''
                        CREATE TABLE message_karma (
                            event_id TEXT NOT NULL,
                            username TEXT(20) DEFAULT NULL,
                            thumbsup int(4) NOT NULL,
                            ok_hand int(4) NOT NULL,
                            heart int(4) NOT NULL
                        )'''
            elif table_list[x] == "user_karma":
                sql = '''
                        CREATE TABLE user_karma (
                            username TEXT NOT NULL,
                            karma int(11) DEFAULT NULL
                        )'''
            elif table_list[x] == "media_hash":
                # Create tables
                sql = '''
                        CREATE TABLE media_hash (
                            event_id TEXT NOT NULL,
                            hash TEXT NOT NULL,
                            date date NOT NULL
                        )'''
            elif table_list[x] == "media_tags":
                # Create tables
                sql = '''
                        CREATE TABLE media_tags (
                            event_id TEXT NOT NULL,
                            tag_member TEXT NOT NULL
                        )'''

            try:
                # Execute the SQL command
                cursor.execute(sql)
            except Exception as e:
                print("Error in check_first_db_run: " + str(e))
                populated_status = False

    cursor.close()
    db.close()

    """ I'm not sure what I was trying accomplish here...
    if populated_status is False:
    # Add group's room_id to the group_members table
    db = sqlite3.connect("db/group_members.db")
    cursor = db.cursor()
    sql = f"ALTER TABLE group_members ADD COLUMN '{database}' TEXT(50)"
    try:
        # Execute the SQL command
        cursor.execute(sql)
    except Exception as e:
        print("Error in populate_db while altering the table" +
                " group_members: " + str(e))
    cursor.close()
    db.close() 
    """

    # Return True if db already existed
    if populated_status:
        print("Success, exiting populate_db()")
    return populated_status


# Retrieve user's karma from the database
async def get_user_karma(database):
    db = await aiosqlite.connect(f"db/{database}.db")
    sql = "SELECT * FROM user_karma WHERE karma <> 0 ORDER BY username;"
    cursor = await db.cursor()
    try:
        # Execute the SQL command
        await cursor.execute(sql)
        # Fetch all the rows in a list of lists.
        results = await cursor.fetchall()

        return_message = "```\n"

        # Find length of longest username and karma
        longest_username_length = 0
        longest_karma_length = 0
        for row in results:
            longest_username_length = max(longest_username_length, len(row[0]))
            longest_karma_length = max(longest_karma_length, len(str(row[1])))

        # Add each user and karma as its own row
        for row in results:
            username = row[0]
            karma_points = row[1]
            return_message += username + (
                " " * (longest_username_length - len(username))) + "   " + (
                    " " * (longest_karma_length -
                           len(str(karma_points)))) + str(karma_points) + "\n"

        return_message += "\n```" + emojize(":v:", use_aliases=True)

    except Exception as e:
        return_message += "Error: " + str(e)
        print("get_user_karma() error: " + str(e))
    finally:
        await cursor.close()
    await db.close()
    return return_message


# Increment the total karma for a specific user
async def update_user_karma(database, username, plus_or_minus, points):
    db = await aiosqlite.connect("db/" + database + ".db")
    sql = "SELECT * FROM user_karma WHERE username = '" + username + "';"
    cursor = await db.cursor()

    try:
        # Execute the SQL command
        await cursor.execute(sql)
        # Fetch one row
        result = await cursor.fetchone()
    except Exception as e:
        print("Error: " + str(e))
    if result is None:
        # Add username to the database along with
        # the points that were just added
        sql = "INSERT INTO user_karma VALUES ('" + username + "', " \
              + points + ");"
        try:
            # Execute the SQL command
            await cursor.execute(sql)
            # Commit your changes in the database
            await db.commit()
        except Exception as e:
            # Rollback in case there is any error
            await db.rollback()
            print("update_user_karma error: " + str(e))
        finally:
            await cursor.close()
    else:
        sql = "UPDATE user_karma SET karma = karma" + plus_or_minus + points \
              + " WHERE username = '" + username + "';"
        try:
            # Execute the SQL command
            await cursor.execute(sql)
            # Commit your changes in the database
            await db.commit()
        except Exception as e:
            # Rollback in case there is any error
            await db.rollback()
            print("update_user_karma error: " + str(e))
        finally:
            await cursor.close()
    await db.close()


# Update a event_id's points
async def update_message_karma(database, event_id, username, query_data,
                               loop):
    user_voted = False

    thumb_points = 0
    ok_points = 0
    heart_points = 0
    # Figure out which column to update
    if int(query_data) == 1:
        emoji_symbol = "thumbsup"
        thumb_points = 1
    elif int(query_data) == 2:
        emoji_symbol = "ok_hand"
        ok_points = 1
    elif int(query_data) == 3:
        emoji_symbol = "heart"
        heart_points = 1

    db = await aiosqlite.connect("db/" + database + ".db")
    sql = "SELECT * FROM message_karma WHERE event_id = " + \
          str(event_id) + " AND username = '" + username + "';"
    cursor = await db.cursor()
    # Check if this event_id exists in the db already
    try:
        # Execute the SQL command
        await cursor.execute(sql)
        # Fetch one row
        result = await cursor.fetchone()
    except Exception as e:
        print("Error: " + str(e))
    if result is None:
        # Insert new row with event_id, username, and emoji point values
        sql = "INSERT INTO message_karma VALUES (" + str(event_id) + ", '" \
              + username + "', " + str(thumb_points) + ", " + str(ok_points) \
              + ", " + str(heart_points) + ");"
        try:
            # Execute the SQL command
            await cursor.execute(sql)
            # Commit your changes in the database
            await db.commit()
        except Exception as e:
            # Rollback in case there is any error
            await db.rollback()
            print("update_message_karma insert error: " + str(e))
        finally:
            await cursor.close()
    else:
        # If user has already voted, check to see if this specific emoji has
        # already been pressed
        if int(query_data) == 1:
            if int(result[2]) != 0:
                # Change specified emoji field to 0 since user is
                # taking back reaction
                sql = "UPDATE message_karma SET thumbsup = 0" \
                    + " WHERE event_id = " + str(event_id) \
                    + " AND username = '" + username + "';"
                user_voted = True
        elif int(query_data) == 2:
            if int(result[3]) != 0:
                # Change specified emoji field to 0 since user is
                # taking back reaction
                sql = "UPDATE message_karma SET ok_hand = 0" \
                    + " WHERE event_id = " + str(event_id) \
                    + " AND username = '" + username + "';"
                user_voted = True
        elif int(query_data) == 3:
            if int(result[4]) != 0:
                # Change specified emoji field to 0 since user is
                # taking back reaction
                sql = "UPDATE message_karma SET heart = 0" \
                    + " WHERE event_id = " + str(event_id) \
                    + " AND username = '" + username + "';"
                user_voted = True
        # If user hasn't already pressed the emoji, add point to db
        if user_voted is False:
            # Update emoji points that user has given a specific event_id
            sql = "UPDATE message_karma SET " + emoji_symbol + " = " \
                + emoji_symbol + " + 1" \
                + " WHERE event_id = " + str(event_id) \
                + " AND username = '" + username + "';"
        try:
            # Execute the SQL command
            await cursor.execute(sql)
            # Commit your changes in the database
            await db.commit()
        except Exception as e:
            # Rollback in case there is any error
            await db.rollback()
            print("update_message_karma error: " + str(e))
        finally:
            await cursor.close()
    await db.close()

    # Return true if user has pressed this emoji already
    # Return false if user has not pressed this emoji already
    return user_voted


# Delete event_id row from database
async def delete_row(database, event_id):
    db = await aiosqlite.connect("db/" + database + ".db")
    # Fetch number of points that need to be deleted
    sql = "SELECT SUM(thumbsup + ok_hand + heart) FROM message_karma " \
          + "WHERE event_id = " + str(event_id) + ";"
    cursor = await db.cursor()

    try:
        # Execute the SQL command
        await cursor.execute(sql)
        # Fetch one row
        points_to_delete = await cursor.fetchone()
    except Exception as e:
        print("Error in delete_row: " + str(e))
    # Delete row that matches event_id
    sql = f"DELETE from message_karma WHERE event_id = {event_id};"
    try:
        # Execute the SQL command
        await cursor.execute(sql)
        # Commit your changes in the database
        await db.commit()
    except Exception as e:
        # Rollback in case there is any error
        await db.rollback()
        print("Error in delete_row: " + str(e))
    finally:
        await cursor.close()
    await db.close()
    return points_to_delete


# Check total karma for specific emoji for a specific message
async def check_emoji_points(database, event_id):
    db = await aiosqlite.connect("db/" + database + ".db")
    sql = "SELECT SUM(thumbsup), SUM(ok_hand), SUM(heart) FROM message_karma" \
          + " WHERE event_id = " + str(event_id) + ";"
    cursor = await db.cursor()

    try:
        # Execute the SQL command
        await cursor.execute(sql)
        # Fetch one row
        result = await cursor.fetchone()
    except Exception as e:
        print("Error in check_emoji_points: " + str(e))
    finally:
        await cursor.close()
    await db.close()
    return result


# Get total karma per user for a specific message
async def get_message_karma(database, event_id):
    return_message = "Votes\n\n"

    db = await aiosqlite.connect("db/" + database + ".db")
    # Multiply ok_hand by 2 and heart by 3 to get correct sum of votes
    sql = "SELECT username, SUM(thumbsup + ok_hand*2 + heart*3) AS karma " \
          + "FROM message_karma WHERE event_id = " + str(event_id) \
          + " GROUP BY username HAVING karma <> 0 ORDER BY username;"
    cursor = await db.cursor()

    try:
        # Execute the SQL command
        await cursor.execute(sql)
        # Fetch all the rows in a list of lists.
        results = await cursor.fetchall()

        # Find length of longest username and karma
        longest_username_length = 0
        longest_karma_length = 0
        for row in results:
            longest_username_length = max(longest_username_length, len(row[0]))
            longest_karma_length = max(longest_karma_length, len(str(row[1])))

        # Add each user and karma as its own row
        for row in results:
            username = row[0]
            karma_points = row[1]
            return_message += username + (
                " " * (longest_username_length - len(username))) + "   " + (
                    " " * (longest_karma_length -
                           len(str(karma_points)))) + str(karma_points) + "\n"
    except Exception as e:
        return_message += "Error"
        print("Error in get_message_karma: " + str(e))
    finally:
        await cursor.close()
    await db.close()
    return return_message


# Get user's personal room_id with Aqua
async def get_room_id(tele_user):
    db = await aiosqlite.connect("db/user_room_ids.db")
    sql = "SELECT room_id FROM user_room_ids WHERE username = '" + str(
        tele_user) + "';"
    cursor = await db.cursor()

    try:
        # Execute the SQL command
        await cursor.execute(sql)
        # Fetch one row
        result = await cursor.fetchone()
    except Exception as e:
        print("Error in get_room_id: " + str(e))
    finally:
        await cursor.close()
    await db.close()
    return result[0]


async def addme_async(chat_type, username, room_id):
    # Make sure the /addme command is being sent in a PM
    if chat_type == "private":
        db = await aiosqlite.connect("db/user_room_ids.db")
        sql = "SELECT * FROM user_room_ids WHERE username = '" + str(
            username) + "';"
        cursor = await db.cursor()

        try:
            # Execute the SQL command
            await cursor.execute(sql)
            # Fetch one row
            result = await cursor.fetchone()
        except Exception as e:
            print("Error: " + str(e))
        if result is None:
            # Add user's room_id with Aqua to database
            sql = "INSERT INTO user_room_ids VALUES (" + str(
                room_id) + ", '" + str(username) + "');"
            try:
                # Execute the SQL command
                await cursor.execute(sql)
                # Commit your changes in the database
                await db.commit()
                message = "Added! Now whenever you " \
                          + emojize(":star:", use_aliases=True) \
                          + " a photo, I'll forward it to you here! " \
                          + emojize(":smiley:", use_aliases=True)
            except Exception as e:
                # Rollback in case there is any error
                await db.rollback()
                print("Adding user's room_id failed. " + str(e))
                message = "Error: " + str(e)
            finally:
                await cursor.close()
        else:
            message = "You've already been added! " + \
                      emojize(":star:", use_aliases=True) + " away :)"
        await db.close()
    else:
        message = "That doesn't work in here. Send me a PM instead " + \
                  emojize(":wink:", use_aliases=True)
    return message


# Store hash of event_id's media in database
async def store_hash(database, event_id, media_hash):
    db = await aiosqlite.connect("db/" + database + ".db")
    # Add event_id, photo's hash, and current date to database
    sql = "INSERT INTO media_hash VALUES ('" + event_id + "','" + media_hash + "', + date('now'));"
    print(sql)
    cursor = await db.cursor()

    try:
        # Execute the SQL command
        await cursor.execute(sql)
        # Commit your changes in the database
        await db.commit()
    except Exception as e:
        # Rollback in case there is any error
        await db.rollback()
        print("Error in store_hash: " + str(e))
    # Delete hashes older than 30 days
    # sql = "DELETE FROM media_hash " \
    #       + "WHERE Date NOT BETWEEN date('now','-30 days') " \
    #       + "AND date('now');"
    # try:
    #     # Execute the SQL command
    #     await cursor.execute(sql)
    #     # Commit your changes in the database
    #     await db.commit()
    # except Exception as e:
    #     # Rollback in case there is any error
    #     await db.rollback()
    #     print("Error in store_hash: " + str(e))
    # finally:
    #     await cursor.close()
    # await db.close()


# Fetch hash of event_id
async def fetch_one_hash(event_id, database):
    db = await aiosqlite.connect("db/" + database + ".db")
    # Fetch a specific event_id's associated hash
    sql = "SELECT hash FROM media_hash WHERE event_id = " + str(
        event_id) + ";"
    cursor = await db.cursor()

    try:
        # Execute the SQL command
        await cursor.execute(sql)
        # Fetch one row
        result = await cursor.fetchone()
    except Exception as e:
        print("Error in fetch_one_hash: " + str(e))
        result = str(e)
    finally:
        await cursor.close()
    await db.close()
    return result


# Fetch the last 30 days of stored hashes
async def fetch_30d_hashes(database):
    db = await aiosqlite.connect("db/" + database + ".db")
    sql = "SELECT event_id, hash FROM media_hash WHERE Date" \
        + " BETWEEN date('now','-30 days') AND date('now');"
    cursor = await db.cursor()

    try:
        # Execute the SQL command
        await cursor.execute(sql)
        # Fetch all the rows in a list of lists.
        result = await cursor.fetchall()
    except Exception as e:
        print("Error in fetch_30d_hashes: " + str(e))
        result = str(e)
    finally:
        await cursor.close()
    await db.close()
    return result


# Fetch all stored hashes
async def fetch_all_hashes(event_id, database):
    db = await aiosqlite.connect("db/" + database + ".db")
    sql = "SELECT event_id, hash FROM media_hash"
    cursor = await db.cursor()

    try:
        # Execute the SQL command
        await cursor.execute(sql)
        # Fetch all the rows in a list of lists.
        result = await cursor.fetchall()
    except Exception as e:
        print("Error in fetch_all_hashes: " + str(e))
        result = str(e)
    finally:
        await cursor.close()
    await db.close()
    return result


# Store tags
async def store_tags(event_id, tags, database):
    db = await aiosqlite.connect("db/" + database + ".db")

    # tags is a list with potentially multiple items
    for x in range(len(tags)):
        # Add event_id, photo's hash
        sql = "INSERT INTO media_tags (event_id, tag_member)" \
            + f' VALUES ({event_id}, "{tags[x]}");'

        cursor = await db.cursor()

        try:
            # Execute the SQL command
            await cursor.execute(sql)
            # Commit your changes in the database
            await db.commit()
        except Exception as e:
            # Rollback in case there is any error
            await db.rollback()
            print(f"Error in store_tags: {e}")
            return False
        finally:
            await cursor.close()
    await db.close()


# Retrieve tags
# TODO: Make sure there aren't duplicates. If there are, return a status code to
# tell main.py to run a table cleaning function
async def retrieve_tags(event_id, tags, database):
    db = await aiosqlite.connect("db/" + database + ".db")

    # tags is a list with potentially multiple items
    for x in range(len(tags)):
        # Add event_id, photo's hash
        sql = f"SELECT tag_member FROM media_tags WHERE event_id={event_id}"
        cursor = await db.cursor()

        try:
            # Execute the SQL command
            await cursor.execute(sql)
            # Fetch all the rows in a list of lists.
            result = await cursor.fetchall()
        except Exception as e:
            print("Error in retrieve_tags: " + str(e))
            result = str(e)
        finally:
            await cursor.close()
        await db.close()
    return result
