from pydantic import BaseModel, ConfigDict, Field, field_validator


class ReportInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    titulo: str = Field(min_length=5, max_length=120)
    descripcion: str = Field(min_length=15, max_length=4000)

    @field_validator("titulo", "descripcion")
    @classmethod
    def reject_null_character(cls, value):
        if "\x00" in value:
            raise ValueError("El texto contiene un carácter nulo.")
        return value
