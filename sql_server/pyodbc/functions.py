from django.db.models.functions import Cast


class TryCast(Cast):
    function = 'TRY_CAST'
