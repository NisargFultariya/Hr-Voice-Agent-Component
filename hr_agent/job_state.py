class JobState:
    """Tracks state parameters during a candidate call session."""
    def __init__(self):
        self.submitted = False
        self.disposition = "completed"
        self.extracted_fields = {}
        self.reasoning = ""
