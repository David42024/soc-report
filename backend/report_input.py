import unicodedata

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ReportInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, hide_input_in_errors=True)
    titulo: str = Field(min_length=5, max_length=120)
    descripcion: str = Field(min_length=15, max_length=4000)

    @field_validator("titulo", "descripcion")
    @classmethod
    def reject_null_character(cls, value: str) -> str:
        """Preserve technical punctuation and line breaks while rejecting unsafe controls."""
        if "\x00" in value:
            raise ValueError("El texto contiene un carácter nulo.")
        if any(unicodedata.category(char) in ("Cc", "Cs") and char not in "\r\n\t" for char in value):
            raise ValueError("El texto contiene caracteres de control no admitidos.")
        if any(unicodedata.bidirectional(char) in ("RLO", "LRO", "RLE", "LRE", "PDF", "RLI", "LRI", "FSI", "PDI") for char in value):
            raise ValueError("El texto contiene controles bidireccionales no admitidos.")
        return value
