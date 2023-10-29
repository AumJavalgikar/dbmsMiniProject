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
import json


ASK_FOR_QUERY = range(1)

class AIQuery:
    def __init__(self, query):
        self.user_query = query
        self.user_followup_responses = []
        self.ai_followup_responses = []
        self.more_info_needed = False
        self.final_sql_queries = None

def parse_response(query, response_text, query_object:AIQuery):
    print(f'In parse response, response_text : {response_text}')
    response_type_regex = re.compile(r'"response_type":\s*"([A-Za-z_]+)"')
    more_info_regex = re.compile(r'"more_info_text":\s*"(.*?)"')
    sql_query_regex = re.compile(r'"sql_queries":\s*"(.*?)"')
    json_response = json.loads(response_text)


    # match = re.search(response_type_regex, response_text)
    # if not match:
    #     raise ValueError('Did not find response_type field in OpenAI response')

    # response_type = match.group(1)
    response_type = json_response.get('response_type')
    if response_type is None:
        raise ValueError('Did not find response_type field in OpenAI response')

    if response_type == 'more_info':
        # match = re.search(more_info_regex, response_text)
        # if not match:
        #     raise ValueError('Did not find a match for more_info_text in response!')

        # more_info_text = match.group(1)
        more_info_text = json_response.get('more_info_text')
        if more_info_text is None:
            raise ValueError('Did not find a match for more_info_text in response!')
        print(f'Appended {more_info_text} to ai_followup responses')
        query_object.ai_followup_responses.append(more_info_text)
        query_object.user_followup_responses.append(query)

    elif response_type == 'sql_queries':
        # match = re.search(sql_query_regex, response_text)
        # if not match:
        #     raise ValueError('Did not find a match for sql_query in response!')
        # sql_query = match.group(1)
        sql_queries = json_response.get('sql_queries')
        if sql_queries is None:
            raise ValueError('Did not find a match for sql_query in response!')
        query_object.final_sql_queries = sql_queries
    else:
        raise ValueError(f'Unknown response type : {response_type}')


async def query_openai_llm(query, query_object: AIQuery):
    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "You are an expert database engineer, you have to create sql queries for the following database schema:\n"
                                          """
                                          mysql> create table administrator(
                                          -> admin_id int,admin_name varchar(20),password int,primary key(admin_id));
                                          
                                          mysql> create table department(
                                          -> dept_id int ,department_name varchar (20),
                                          -> primary key(dept_id));
                                          
                                          mysql> create table student(
                                          -> roll_no int,s_name varchar(20),address varchar(20),cont_no int,primary key(roll_no))
                                          -> dept_id references department(dept_id);
                                          
                                          mysql> create table course(
                                          -> course_id int, c_name varchar (20),qualification varchar(20),experience varchar(20),dept_id int,
                                          -> foreign key (dept_id) references department(dept_id));
                                                                          
                                          mysql> create table attendance(
                                        -> dept_id int,roll_no int,s_name varchar (20),course varchar(20),percentage int,
                                        -> foreign key (roll_no) references student(roll_no),
                                        -> foreign key (dept_id) references department(dept_id));
                                        
                                        mysql> create table section(
                                        -> section_id int,section_name varchar (20),dept_id int ,
                                        -> primary key(section_id),
                                        -> foreign key (dept_id) references department(dept_id));
                                          
                                        mysql> create table exam(
                                        -> reg_no int,marks int,course varchar(20),
                                        -> dept_id int,
                                        -> primary key(reg_no),
                                        -> foreign key (dept_id) references department(dept_id));
                                          """
                                          "Your conversation history with the client:\n"
                                          f"User responses : {query_object.user_followup_responses}\n"
                                          f"Your responses : {query_object.ai_followup_responses}\n\n"
                                          f'If you need more information you MUST ask the client for more info\n'
                                          f'if the client is asking to insert information they MUST provide values for EVERY field\n'
                                          f'Same goes for other things, like creating tables, even fetching data!\n'
                                          f' if you have sufficient information go ahead and create the sql query.\n'
                                          f'you MUST generate the response in the following json format:'
                                          f'{{"response_type": \"more_info\"/\"sql_queries\"\n'
                                          f'more_info_text: \"request client for more information according to your needs within quotes\"\n'
                                          f'sql_queries: ["generate sql query according to the clients needs within double quotes, generate more than one if needed",'
                                          f'"sql query 2", "sql query 3"...]}}\n'

             },
            {"role": "user", "content": f'The client has communicated the following :\n\n'
                                        f'{query}\n\n'
                                        f'Before generating the information, take a deep breath, look at the rules provided before generating the response, '
                                        f'Now generate ONLY the json response, do not include any additional text besides the json response, {{..'
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


def evaluate_query(sql_query: str):

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
        return f'create operation successful!'

    elif 'drop' in sql_query.lower():
        mydb.commit()
        return f'drop operation successful!'

    elif 'update' in sql_query.lower():
        mydb.commit()
        return f'successfully updated {mycursor.rowcount} row (s)'

    elif 'insert' in sql_query.lower():
        mydb.commit()
        return f'successfully inserted {mycursor.rowcount} row (s)'

    elif 'alter' in sql_query.lower():
        mydb.commit()
        return f'alter operation successful!'

    elif 'select' or 'show' in sql_query.lower():
        results = mycursor.fetchall()
        columns = f"{' '.join(key for key in results[0].keys())}\n"
        return columns + '\n'.join([' '.join([str(element) for element in inner_dict.values()]) for inner_dict in results])

    else:
        mydb.commit()
        return 'operation successful!'


async def query_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.effective_message.text
    query_object: AIQuery = context.user_data.setdefault('query_info', AIQuery(query=query))
    await query_openai_llm(query, query_object=query_object)
    print(f'ai_followup responses : {query_object.ai_followup_responses}')
    print(f'user_followup responses : {query_object.user_followup_responses}')

    if query_object.final_sql_queries is None:
        await update.effective_message.reply_text(query_object.ai_followup_responses[-1])
        return ASK_FOR_QUERY

    query_results = []
    for query in query_object.final_sql_queries:
        query_results.append(evaluate_query(query))

    query_results = '\n'.join(query_results)
    await update.effective_message.reply_text(f'Here is the result of your query:\n\n{query_results}\n\nTo start a new query use command /aiquery')
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