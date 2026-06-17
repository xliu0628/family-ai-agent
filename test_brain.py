import os
from google import genai

def main():
    # Verify the project ID is available
    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not project:
        print("❌ Error: GOOGLE_CLOUD_PROJECT environment variable is missing.")
        return

    print(f"Initializing Gemini Client via Vertex AI backend configuration...")
    
    # When GOOGLE_GENAI_USE_VERTEXAI=true is set in the terminal,
    # genai.Client() automatically hooks into Vertex AI using your ambient settings.
    client = genai.Client()

    # Pass only the direct model identifier.
    response = client.models.generate_content(
        model='gemini-2.5-flash', 
        contents='Respond with exactly: "The agent brain is online."',
    )

    print("\n--- Response From Gemini ---")
    print(response.text.strip())

if __name__ == '__main__':
    main()
