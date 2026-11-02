from django.shortcuts import render

from stations.index import warm


def index(request):
    warm()
    return render(
        request,
        "web/index.html",
        {"start": request.GET.get("start", ""), "finish": request.GET.get("finish", "")},
    )
