(function () {
  var ACCENT = "#1d4e89";
  var form = document.getElementById("plan-form");
  var button = document.getElementById("submit");
  var errorEl = document.getElementById("error");
  var resultsEl = document.getElementById("results");
  var stopsEl = document.getElementById("stops");

  var map = L.map("map").setView([39.5, -98.35], 4);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 18,
    attribution: "&copy; OpenStreetMap contributors"
  }).addTo(map);
  var layer = L.layerGroup().addTo(map);

  function money(n) { return "$" + n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
  function cell(text, cls) {
    var td = document.createElement("td");
    td.textContent = text;
    if (cls) td.className = cls;
    return td;
  }

  function showError(message) {
    errorEl.textContent = message;
    errorEl.hidden = false;
    resultsEl.hidden = true;
  }

  function render(data) {
    errorEl.hidden = true;
    layer.clearLayers();

    var line = L.geoJSON(data.route, { style: { color: ACCENT, weight: 3 } }).addTo(layer);
    [data.start, data.finish].forEach(function (p) {
      L.circleMarker([p.lat, p.lng], { radius: 5, color: ACCENT, fillColor: "#fff", fillOpacity: 1, weight: 2 })
        .bindTooltip(p.query).addTo(layer);
    });

    var markers = {};
    stopsEl.textContent = "";
    data.fuel_stops.forEach(function (s) {
      var marker = L.marker([s.lat, s.lng], {
        icon: L.divIcon({ className: "", html: '<div class="stop-marker">' + s.order + "</div>", iconSize: [24, 24] })
      }).addTo(layer);
      marker.bindPopup(
        document.createTextNode(s.name + ", $" + s.price_per_gallon.toFixed(3) + "/gal, " + s.gallons.toFixed(1) + " gal")
      );
      markers[s.order] = marker;

      var tr = document.createElement("tr");
      tr.tabIndex = 0;
      var station = cell(s.name);
      var where = document.createElement("small");
      where.textContent = s.city + ", " + s.state + (s.off_route_miles >= 1 ? ", about " + s.off_route_miles.toFixed(0) + " mi off route" : "");
      station.appendChild(where);
      tr.append(cell(s.order), station, cell(s.mile.toFixed(0), "num"), cell("$" + s.price_per_gallon.toFixed(3), "num"),
        cell(s.gallons.toFixed(1), "num"), cell(money(s.cost), "num"));
      function focusStop() { map.setView([s.lat, s.lng], Math.max(map.getZoom(), 8), { animate: false }); markers[s.order].openPopup(); }
      tr.addEventListener("click", focusStop);
      tr.addEventListener("keydown", function (e) { if (e.key === "Enter") focusStop(); });
      stopsEl.appendChild(tr);
    });

    document.getElementById("r-distance").textContent = data.distance_miles.toFixed(1) + " mi";
    document.getElementById("r-gallons").textContent = data.total_gallons.toFixed(1) + " gal";
    document.getElementById("r-cost").textContent = money(data.total_cost);

    var notes = [];
    if (data.origin_fill_estimated) notes.push("The first fill is priced at the first station on the route; none was within 50 miles of the start.");
    if (data.fuel_stops.length && data.fuel_stops[0].mile >= 1) {
      notes.push("The first fill also covers the " + data.fuel_stops[0].mile.toFixed(0) + " miles before that station.");
    }
    if (data.cached) {
      notes.push("Served from cache in " + data.timing_ms.total + " ms.");
    } else {
      notes.push("Computed in " + data.timing_ms.total + " ms, of which " + data.timing_ms.routing + " ms was the routing API.");
    }
    document.getElementById("r-note").textContent = notes.join(" ");

    resultsEl.hidden = false;
    map.invalidateSize();
    map.fitBounds(line.getBounds(), { padding: [32, 32], animate: false });
  }

  function submit() {
    var start = form.start.value.trim();
    var finish = form.finish.value.trim();
    if (!start || !finish) { showError("Enter a start and a finish."); return; }

    button.disabled = true;
    button.textContent = "Planning...";
    fetch("/api/v1/route-plan/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ start: start, finish: finish })
    })
      .then(function (res) { return res.json().then(function (body) { return { ok: res.ok, body: body }; }); })
      .then(function (r) {
        if (!r.ok) { showError(r.body.error ? r.body.error.message : "Request failed."); return; }
        render(r.body);
        history.replaceState(null, "", "/?" + new URLSearchParams({ start: start, finish: finish }));
      })
      .catch(function () { showError("Could not reach the server."); })
      .finally(function () { button.disabled = false; button.textContent = "Plan route"; });
  }

  form.addEventListener("submit", function (e) { e.preventDefault(); submit(); });
  if (form.start.value && form.finish.value) submit();
})();
