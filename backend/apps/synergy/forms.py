from __future__ import annotations

from django import forms

from .models import SynergyCredential


class SynergyCredentialForm(forms.ModelForm):
    password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=False),
        help_text="Введите новый пароль Synergy (старый пароль не отображается). Оставьте пустым, чтобы не менять.",
    )

    class Meta:
        model = SynergyCredential
        fields = ("student", "login", "password")

    def save(self, commit: bool = True):
        obj: SynergyCredential = super().save(commit=False)
        raw_password = (self.cleaned_data.get("password") or "").strip()
        if raw_password:
            obj.set_password(raw_password)
        if commit:
            obj.save()
        return obj

