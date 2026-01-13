from __future__ import annotations

from django import forms

from apps.accounts.models import Student


class StudentLoginForm(forms.Form):
    """Форма входа для студентов (по external_id или email)."""

    identifier = forms.CharField(
        label="Email или ID",
        max_length=255,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "email@example.com или ваш ID"}),
    )

    def clean_identifier(self):
        identifier = self.cleaned_data.get("identifier", "").strip()
        if not identifier:
            raise forms.ValidationError("Введите email или ID")
        return identifier

    def get_student(self) -> Student | None:
        """Найти студента по identifier (email или external_id)."""
        identifier = self.cleaned_data.get("identifier", "").strip()
        if not identifier:
            return None

        # Пробуем по email
        student = Student.objects.filter(email__iexact=identifier, is_active=True).first()
        if student:
            return student

        # Пробуем по external_id
        student = Student.objects.filter(external_id=identifier, is_active=True).first()
        if student:
            return student

        return None


class StudentRegisterForm(forms.ModelForm):
    """Форма регистрации нового студента."""

    class Meta:
        model = Student
        fields = ("full_name", "email", "phone", "external_id")
        widgets = {
            "full_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ваше имя"}),
            "email": forms.EmailInput(attrs={"class": "form-control", "placeholder": "email@example.com"}),
            "phone": forms.TextInput(attrs={"class": "form-control", "placeholder": "+7 (999) 123-45-67"}),
            "external_id": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Ваш ID (например, Telegram user_id)"}
            ),
        }

    def clean_email(self):
        email = self.cleaned_data.get("email", "").strip()
        if email and Student.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Студент с таким email уже зарегистрирован")
        return email

    def clean_external_id(self):
        external_id = self.cleaned_data.get("external_id", "").strip()
        if external_id and Student.objects.filter(external_id=external_id).exists():
            raise forms.ValidationError("Студент с таким ID уже зарегистрирован")
        return external_id
