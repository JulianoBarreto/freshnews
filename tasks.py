import logging
import sys
from robocorp.tasks import task
from RPA.Assistant import Assistant
import requests
import json
import traceback
import warnings
import re
import os
# from robocorp import browser
# from RPA.HTTP import HTTP
from RPA.Excel.Files import Files
from openai import OpenAI


# Logging Config:
stdout = logging.StreamHandler(sys.stdout)
logging.basicConfig(
    level=logging.DEBUG,
    format="[{%(filename)s:%(lineno)d} %(levelname)s - %(message)s",
    # handlers=[stdout], 
    filename="output/output.log",
)
LOGGER = logging.getLogger(__name__)

# OpenAI Configurations:
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))  # TODO: Need to put this API KEY in the vault.
model = "gpt-4o"
prompt = ("You are a news specialist. Your job is to open all the Reuters news links below and use all the information gathered to answer the " 
            "user's question. You MUST OPEN all the Reuters links provided:"
            "Reuters News Links:"
            "%news_links%")

@task
def robot_main_core():
    """
    Main core to the bot. The bot search and save news filtering by search phrase, category and date.
    First the bot will work only with Reuter's news.
    """

    # Open a window to get the filters from user:
    p = get_filters()
    # Temp. OBS.: "2024-06-30T22:51:31.145Z"
    parameters = {"phrase":p.phrase, "category":"", "start_date":p.start_date, "end_date":p.end_date, "img_size":p.img_size}

    # Search for the news using the parameters:
    try:
        articles = get_news_from_reuters(parameters)
    except ValueError as v:
        error_msg = "An error occured! Please consider this information: VALUE Error: %s, TRACEBACK: %s" % (v, traceback.format_exc())
        popup_message(error_msg, "error")
    except UserWarning as w:
        popup_message(w, "warning")
    
    # Saving the response in an Excel file: 
    qt_news = save_data_excel(parameters, articles)
    popup_message(f"All done! {qt_news} was found and saved.")

    # Opening the Advisor:
    advisor_window(articles)
    # msg = False
    # while True:
    #    response = advisor_window(msg)
    #    print(response)
    #    if response is False:
    #        break
    #    else:
    #        response = advisor_window(response)


def get_filters():
    """ 
        Shows a window and get the parameters to search and filter the news. 

        Parameters: 
        None

        Returns:
        dict: Dictionary with all the parameters selected by user (search phrase, start date, end date and image size).
    """
    assistant = Assistant()
    assistant.add_heading("Select Your Filters")
    assistant.add_text_input("phrase", default="coffee", label="Search Phrase")
    assistant.add_date_input("start_date", default="2024-06-30", label="Start Date")
    assistant.add_date_input("end_date", default="2024-07-02", label="End Date")
    assistant.add_drop_down(
        name="img_size",
        options="60w,120w,240w,480w,960w,1080w,1200w,1920w",
        default="1080w",
        label="Image Width"
    )
    assistant.add_submit_buttons("Submit", default="Submit")
    result = assistant.run_dialog()
    return result


def get_news_from_reuters(par):
    """
        Get the news from Reuters using the paramenters.

        Parameter:
        par(dict): The parameters passed by user (phrase to search, start date, end date, image size to recover).

        Returns:
        dict: Articles found with id, url, title, headline, description, publish date, update date, image url, 
                thumbnail url, image description, number of times the phrase appears, if money appears.
    """
    main_url = "https://www.reuters.com"
    offset_size = 100  # Number of news to retrieve per page.
    offset = 0  # The offset - actual news.
    url = 'https://www.reuters.com/pf/api/v3/content/fetch/articles-by-search-v2?query=\
            {"end_date":"' + par['end_date'].strftime('%Y-%m-%d') + '", \
            "keyword":"' + par['phrase'] + '", "offset":"' + str(offset) + '", \
            "orderby":"display_date:desc", "size":"' + str(offset_size) + '", \
            "start_date":"' + par['start_date'].strftime('%Y-%m-%d') + '", \
            "website":"reuters"}&d=201&_website=reuters'

    LOGGER.info("Getting the news from %s until %s. Searching for '%s'..." % (par['start_date'], par['end_date'], par['phrase']))

    r = requests.get(url)
    response = json.loads(r.text)
    # If the message doesn't return "Success", there's nothing we can do except raise an error:
    message = response['message']
    if message != "Success":  
        raise ValueError(message)
    # If theresn't news, raise a warning:
    total_news = response['result']['pagination']['total_size']
    if total_news <= 0:
        warnings.warn("The search returned 0 results", UserWarning)

    articles= []

    while True:
        # Organizing the articles: 
        for article in response['result']['articles']:
            articles.append({
                'art_id': article['id'],
                'art_url': main_url + article['canonical_url'],
                'title': article['title'],
                'headline': article['basic_headline'],
                'desc': article['description'],
                'pub_date': article['published_time'],
                'upd_date': article['updated_time'],
                'img_url': article['thumbnail']['renditions']['original'][par['img_size']],  # 60w 120w 240w 480w 960w 1080w 1200w 1920w
                'thumb_url': article['thumbnail']['renditions']['square']['120w'],  # 60w 120w 240w 480w 960w 1080w 1200w 1920w
                'img_desc': article['thumbnail']['caption'] if 'caption' in article['thumbnail'] else "No Caption",  # Description of the image.
                'count_phrase': count_searched_phrase(par['phrase'], article['title']) + count_searched_phrase(par['phrase'], article['description']),  
                'contains_money': contains_money(article['title']) or contains_money(article['description']),  # Test if title or desc contains money.
            })
            offset += 1
        if offset >= total_news:  # If all news was collected, end the loop.
            break
        if offset >= offset_size:  # if have more than 'offset_size' news. Works like pagination.
            url = 'https://www.reuters.com/pf/api/v3/content/fetch/articles-by-search-v2?query=\
            {"end_date":"' + par['end_date'].strftime('%Y-%m-%d') + '", \
            "keyword":"' + par['phrase'] + '", "offset":"' + str(offset) + '", \
            "orderby":"display_date:desc", "size":"' + str(offset_size) + '", \
            "start_date":"' + par['start_date'].strftime('%Y-%m-%d') + '", \
            "website":"reuters"}&d=201&_website=reuters'

            r = requests.get(url)
            response = json.loads(r.text)

    LOGGER.info("Success!")
    return articles


def save_data_excel(par, articles):
    """
    Saves all the retrieved data in an Excel .xlsx file.

    Parameters:
    par (dict): Search parameters used to retrieve the articles.
    articles (list): List of articles retrieved from the search.

    Returns:
    int: Number of news articles saved.
    """
    qt_news_saved = 0
    excel = Files()
    filename = f"output/FreshNews[{par['phrase']}] {par['start_date']}-{par['end_date']}.xlsx"
    excel.create_workbook(filename)
    # excel.create_worksheet("FreshNews")

    LOGGER.info(f"Creating the file with name '{filename}'.")

    col_titles = articles[0].keys()  # Get the titles of the columns
    # rows = [list(col_titles)]  # Starting the rows (with the titles)
    rows = [list(["ID", "News URL", "Title", "Headline", "Description", "Publish Date", "Last Update Date", "Image URL", 
                  "Thumb URL", "Image Description", "Count Phrase", "Contains Money"])]  # Starting the rows (with the titles)

    for article in articles:
        rows.append(list(article.values()))
        qt_news_saved += 1

    excel.append_rows_to_worksheet(rows)  # , header=True, start=2)
    excel.auto_size_columns("A", "L")
    excel.save_workbook()
    excel.close_workbook()
    LOGGER.info("File saved!")

    return qt_news_saved 


def popup_message(msg, type=None):
    """ 
        This function shows a Pop-up window with 'error', 'warning' or 'info' (type parameter). It's also save
        the log with the message.

        Parameters:
        msg (string): Message to show in the pop-up window.
        type (None, 'error', 'warning'): Defines the pop-up style (Info, Error or Warning).

        Returns:
        Nothing.
    """
    popup = Assistant()
    if type == "error":
        LOGGER.error(msg)
        title = "Error"
        icon = "failure"
        head = "An Error Ocurred"
    elif type == "warning":
        LOGGER.warning(msg)
        title = "Warning"
        icon = "warning"
        head = "A Warning Raised"
    else:
        LOGGER.info(msg)
        title = "Info"
        icon = "success"
        head = "Information"

    popup.add_icon(icon)
    popup.add_heading(head)
    popup.add_text(msg)
    popup.add_submit_buttons("Ok")
    popup.run_dialog(title=title)


def contains_money(str):
    """ Test if a string 'str' contains any kind of money using Regex (Possible formats: $11.1 | $111,111.11 | 11 dollars | 11 USD). 

        Parameter: 
        str (string): String to find money reference. 

        Returns: 
        boolean: Found (True) or not (False).
    """
    money_pattern = re.compile(r'\$\d+(?:,\d{3})*(?:\.\d{2})?|\d+ dollars|\d+ USD')

    if money_pattern.search(str):
        return True
    return False


def count_searched_phrase(phrase, str):
    """ 
        Counts how often the 'phrase' appears in the string 'str'. 

        Parameters:
        phrase(string): The needle to search for.
        str(string): The string to serch for the needle.

        Returns:
        int: Number of times the needle was found.
    """
    return str.lower().count(phrase.lower())


def advisor(message, articles):
    """
        Use the OpenAI API to consult the results with the question of the user.

        Parameters:
        message(string): User's question.
        articles(dict): The found news articles.

        Returns:
        string: The IA's answer.

    """
    global client, model, prompt
    links = ""    

    for article in articles:
        links = links + article['art_url'] + "\n"
    conversation = [{"role": "system", "content": prompt.replace("%news_links%", links)},]
    conversation.append({"role": "user", "content": message})
    chat = client.chat.completions.create(
        model=model, messages=conversation, # user=str(u_code)
    )
    reply = chat.choices[0].message.content
    conversation.append({"role": "assistant", "content": reply})
    return reply


def advisor_window(articles):
    """
        Open a window to user ask something to IA, based on the found news.

        Parameters:
        articles(dict): The news articles found.

        Returns:
        Boolen: True when user select "Exit".
    """
    LOGGER.info("Starting the A.I. Bot...")
    # assistant.add_image("bot-face.jpeg")
    message = None
    while True:
        assistant = Assistant()
        assistant.add_heading("Talk with the AI About The Found News", size="large")

        if message is not None:
            assistant.add_text(f"YOU:\n{message}")
            response = advisor(message, articles)
            LOGGER.info(f"The A.I. responded: {response}")
            assistant.add_text(f"A.I.:\n{response}")
        assistant.add_text_input("message", label="Ask Something")
        assistant.add_submit_buttons(buttons="Send Message, Exit", default="Send Message")
        result = assistant.run_dialog(title="Large", height=600, width=800)
        if result.submit == "Exit":
            LOGGER.info("'Exit' Selected. Exiting...")
            return True
        else:
            LOGGER.info(f"Asked a question: {result.message}")
            message = result.message

