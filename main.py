from telegram.ext import (ApplicationBuilder,
                          CommandHandler, MessageHandler, filters, ContextTypes,
                          ConversationHandler, CallbackQueryHandler)
from telegram import Update
import openai
import logging
import re
import mysql.connector
from dotenv import load_dotenv
import os


ASK_FOR_QUERY = range(1)

class AIQuery:
    def __init__(self, query):
        self.user_query = query
        self.user_followup_responses = []
        self.ai_followup_responses = []
        self.more_info_needed = False
        self.final_sql_query = None

def parse_response(query, response_text, query_object:AIQuery):
    print(f'In parse response, response_text : {response_text}')
    response_type_regex = re.compile(r'"response_type":\s*"([A-Za-z_]+)"')
    more_info_regex = re.compile(r'"more_info_text":\s*"(.*?)"')
    sql_query_regex = re.compile(r'"sql_query":\s*"(.*?)"')

    match = re.search(response_type_regex, response_text)
    if not match:
        raise ValueError('Did not find response_type field in OpenAI response')

    response_type = match.group(1)

    if response_type == 'more_info':
        match = re.search(more_info_regex, response_text)
        if not match:
            raise ValueError('Did not find a match for more_info_text in response!')
        more_info_text = match.group(1)
        print(f'Appended {more_info_text} to ai_followup responses')
        query_object.ai_followup_responses.append(more_info_text)
        query_object.user_followup_responses.append(query)

    elif response_type == 'sql_query':
        match = re.search(sql_query_regex, response_text)
        if not match:
            raise ValueError('Did not find a match for sql_query in response!')
        sql_query = match.group(1)
        query_object.final_sql_query = sql_query
    else:
        raise ValueError(f'Unknown response type : {response_type}')


async def query_openai_llm(query, query_object: AIQuery):
    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "You are an expert database engineer, you have to create sql queries for the following database schema:\n"
                                          "Student("
                                          "student_id int primary key,"
                                          "name varchar(20));\n"
                                          "registration("
                                          "reg_id int primary key,"
                                          "student_id int references Student(student_id)"
                                          ");"
                                          "CREATE TABLE attendance (AID int primary key, month int, year int, student_id int references Student(student_id));"
                                          "Your conversation history with the client:\n"
                                          f"User responses : {query_object.user_followup_responses}\n"
                                          f"Your responses : {query_object.ai_followup_responses}\n\n"
                                          f'If you need more information you MUST ask the client for more info\n'
                                          f'if the client is asking to insert information they MUST provide values for EVERY field\n'
                                          f'Same goes for other things, like creating tables, even fetching data!\n'
                                          f' if you have sufficient information go ahead and create the sql query.\n'
                                          f'you MUST generate the response in the following format:'
                                          f'{{response_type: \"more_info\"/\"sql_query\"\n'
                                          f'more_info_text: \"request client for more information according to your needs within quotes\"\n'
                                          f'sql_query: \"generate sql query according to the clients needs within double quotes\"\n'

             },
            {"role": "user", "content": f'The client has communicated the following :\n\n'
                                        f'{query}\n\n'
                                        f'Before generating the information, take a deep breath, look at the rules provided and generate your response now, '
                                        f'make sure no additional information is required from the client, better safe than sorry.'
                                        f'Now generate the response.'
             },
            {"role": "assistant", "content": ""},
        ]
    )
    response_text = response['choices'][0]['message']['content']
    parse_response(query, response_text, query_object)

    print(response_text)


async def instructions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text('This is a centralised student management system!')


async def ai_sql_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text('You can ask for any information from the database or '
                                              'insert any information into the database in your natural language!\n\n'
                                              'for example: Show all students in division B.')
    return ASK_FOR_QUERY


def evaluate_query(query_object: AIQuery):
    sql_query = query_object.final_sql_query

    mydb = mysql.connector.connect(
        host="localhost",
        user="root",
        password="manager",
        database="student_management"
    )
    mycursor = mydb.cursor(dictionary=True)
    mycursor.execute(sql_query)

    if 'create' in sql_query.lower():
        mydb.commit()
        return f'operation successful!'

    elif 'update' in sql_query.lower():
        mydb.commit()
        return f'successfully updated {mycursor.rowcount} row (s)'

    elif 'insert' in sql_query.lower():
        mydb.commit()
        return f'successfully inserted {mycursor.rowcount} row (s)'

    elif 'select' in sql_query.lower():
        results = mycursor.fetchall()
        columns = f"{' '.join(key for key in results[0].keys())}\n"
        return columns + '\n'.join([' '.join([str(element) for element in inner_dict.values()]) for inner_dict in results])

    else:
        mydb.commit()
        return 'operation successful!'



async def query_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.effective_message.text
    query_object = context.user_data.setdefault('query_info', AIQuery(query=query))
    await query_openai_llm(query, query_object=query_object)
    print(f'ai_followup responses : {query_object.ai_followup_responses}')
    print(f'user_followup responses : {query_object.user_followup_responses}')

    if query_object.final_sql_query is None:
        await update.effective_message.reply_text(query_object.ai_followup_responses[-1])
        return ASK_FOR_QUERY

    query_result = evaluate_query(query_object)
    await update.effective_message.reply_text(f'Here is the result of your query:\n\n{query_result}\n\nTo start a new query use command /aiquery')
    context.user_data.clear()
    return ConversationHandler.END



def create_app(bot_token, openai_token):
    openai.api_key = openai_token
    new_application = (
        ApplicationBuilder()
        .token(bot_token)
        .build()
    )
    _set_logging()
    return new_application


def add_handlers(application):
    application.add_handler(CommandHandler('start', instructions))
    application.add_handler(ConversationHandler(entry_points=[CommandHandler('aiquery', ai_sql_entry)],
    states={ASK_FOR_QUERY: [MessageHandler(filters.TEXT, query_received)]},
    fallbacks=[]
    ))
    application.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT, instructions))


def _set_logging():
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)


if __name__ == '__main__':
    load_dotenv('secrets/secrets.env')
    bot_token = os.getenv('BOT_TOKEN')
    open_ai_key = os.getenv('OPENAI_API_KEY')
    app = create_app(bot_token=bot_token, openai_token=open_ai_key)
    add_handlers(app)
    app.run_polling()