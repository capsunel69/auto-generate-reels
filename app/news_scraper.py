from bs4 import BeautifulSoup
import requests
from openai import OpenAI
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def scrape_news_content(url):
    """Scrape the main content from a news article URL."""
    try:
        # Add headers to mimic a browser request
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Remove script and style elements
        for script in soup(['script', 'style']):
            script.decompose()
            
        # Extract text from paragraphs
        paragraphs = soup.find_all('p')
        content = ' '.join([p.get_text().strip() for p in paragraphs])
        
        # Get the title
        title = soup.find('title')
        title_text = title.get_text() if title else ''
        
        return {
            'title': title_text,
            'content': content
        }
    except Exception as e:
        raise Exception(f"Failed to scrape the URL: {str(e)}")

def generate_tiktok_script(article_data):
    """Generate a TikTok script using OpenAI based on the article content."""
    try:
        client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
        
        print("\nPreparing OpenAI request...")
        print(f"Article title: {article_data['title']}")
        print(f"Content length: {len(article_data['content'])} characters")
        
        prompt = f"""
        Title: {article_data['title']}
        Content: {article_data['content'][:1000]}  # Limiting content length for API
        
        Create a short, engaging script in Romanian for a TikTok news video (30-60 seconds). 
        The script should:
        - Start with an extremely captivating hook in the first 3 seconds
        - Use pattern interrupts or shocking facts to grab attention
        - Be conversational and engaging
        - Focus on the most important facts
        - Be clear and concise
        - Use simple Romanian language that's easy to understand
        - Be around 100-150 words
        - Only include the script text, no suggestions or additional formatting
        
        Important: The entire response must be in Romanian language.
        """
        
        print("\nSending request to OpenAI...")
        print("Waiting for response...")
        
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are a skilled Romanian news script writer for social media, specialized in creating viral hooks."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=1000,
            temperature=0.7
        )
        
        print("\nResponse received from OpenAI!")
        print("\nFull API Response:")
        print("-" * 50)
        print(response)
        print("-" * 50)
        
        # Check if the response was cut off
        script = response.choices[0].message.content.strip()
        if response.choices[0].finish_reason != "stop":
            print("\nWarning: The response might have been cut off!")
            print(f"Finish reason: {response.choices[0].finish_reason}")
        
        return script
    
    except Exception as e:
        raise Exception(f"Failed to generate script: {str(e)}")

def create_news_script(url):
    """Main function to create a script from a news URL."""
    try:
        # Step 1: Scrape the content
        article_data = scrape_news_content(url)
        
        # Step 2: Generate the script
        script = generate_tiktok_script(article_data)
        
        return script
        
    except Exception as e:
        raise Exception(f"Error creating news script: {str(e)}")

if __name__ == "__main__":
    # Example usage
    url = input("Enter the news article URL: ")
    try:
        print("\nStarting script generation process...")
        print(f"Processing URL: {url}")
        
        script = create_news_script(url)
        
        print("\nGenerated Script:")
        print("=" * 50)
        print(script)
        print("=" * 50)
        
        # Add word count
        word_count = len(script.split())
        print(f"\nScript word count: {word_count} words")
        
    except Exception as e:
        print(f"Error: {str(e)}")
