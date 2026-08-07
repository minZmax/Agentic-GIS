(function () {
  "use strict";

  const map = L.map('map', {
    preferCanvas: true
  }).setView([37.658, 126.835], 12);

  L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png', {
    maxZoom: 19
  }).addTo(map);

  const analysisLayerGroup = L.featureGroup().addTo(map);

  let currentChart = null;
  const referenceLayers = {};
  const layerControl = L.control.layers({}, referenceLayers, { collapsed: false, position: "topright" }).addTo(map);
  const $ = (id) => document.getElementById(id);

  function esc(value) { 
    const el = document.createElement("span"); 
    el.textContent = value ?? ""; 
    return el.innerHTML; 
  }

  // 💡 [안전 강화] [0,0] 좌표나 NaN 값은 원천 필터링
  function isValidCoord(c) {
    if (!Array.isArray(c) || c.length < 2) return false;
    const lng = Number(c[0]);
    const lat = Number(c[1]);
    if (!Number.isFinite(lng) || !Number.isFinite(lat)) return false;
    if (lng === 0 && lat === 0) return false; 
    return true;
  }

  // 💡 [줌투레이어 개선] [lat,lng] / [lng,lat] 순서가 섞여 와도 안전하게 보정
  function toLatLng(coord) {
    let lng = Number(coord[0]);
    let lat = Number(coord[1]);
    if (lng >= 30 && lng <= 45 && lat >= 120 && lat <= 135) {
      const tmp = lng; lng = lat; lat = tmp; // 서버가 [lat, lng] 순서로 보낸 경우 보정
    }
    return [lat, lng];
  }

  // 💡 [줌투레이어 개선] Leaflet 레이어의 getBounds() 체인에 의존하지 않고
  // 서버가 보내준 GeoJSON 좌표에서 직접 범위를 계산 (더 안전하고 실패 확률 낮음)
  function computeBoundsFromGeoJSON(geojson) {
    const bounds = new L.LatLngBounds();
    (geojson.features || []).forEach((feature) => {
      const geom = feature && feature.geometry;
      if (!geom || !geom.coordinates) return;
      const walk = (coords) => {
        if (!Array.isArray(coords)) return;
        if (typeof coords[0] === "number") {
          const [lat, lng] = toLatLng(coords);
          if (Number.isFinite(lat) && Number.isFinite(lng)) bounds.extend([lat, lng]);
        } else {
          coords.forEach(walk);
        }
      };
      walk(geom.coordinates);
    });
    return bounds;
  }

  function clearLayer() { 
    try {
      analysisLayerGroup.clearLayers(); 
      $("mapLegend").classList.remove("active"); 
    } catch(e) {
      console.warn("레이어 초기화 예외 방어:", e);
    }
  }

  function getGraduatedStyle(passengers, maxVal, isSubway) {
    const ratio = maxVal > 0 ? Math.min(Math.max(passengers / maxVal, 0), 1) : 0.5;
    const radius = Math.round(7 + ratio * 9);
    
    let color = '#3b82f6';
    if (isSubway) {
      if (ratio >= 0.75) color = '#7e22ce';
      else if (ratio >= 0.5) color = '#dc2626';
      else if (ratio >= 0.25) color = '#f97316';
      else color = '#eab308';
    } else {
      if (ratio >= 0.75) color = '#581c87';
      else if (ratio >= 0.5) color = '#1d4ed8';
      else if (ratio >= 0.25) color = '#0284c7';
      else color = '#38bdf8';
    }

    return { radius, color, ratio };
  }

  function renderAnalyticsChart(chartData) {
    const container = $("chartContainer");
    const canvas = $("analyticsChart");
    if (!container || !canvas) return;

    if (!chartData || chartData.length === 0) {
      container.style.display = "none";
      return;
    }

    container.style.display = "block";

    if (currentChart) {
      currentChart.destroy();
    }

    const labels = chartData.map(item => item.label);
    const values = chartData.map(item => item.value);

    if (typeof Chart !== "undefined") {
      currentChart = new Chart(canvas, {
        type: 'bar',
        data: {
          labels: labels,
          datasets: [{
            label: '총 이용량 (명)',
            data: values,
            backgroundColor: 'rgba(147, 51, 234, 0.75)',
            borderColor: '#c084fc',
            borderWidth: 1,
            borderRadius: 4
          }]
        },
        options: {
          indexAxis: 'y',
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { display: false } },
          scales: {
            x: { grid: { color: '#334155' }, ticks: { color: '#94a3b8', font: { size: 10 } } },
            y: { grid: { display: false }, ticks: { color: '#f8fafc', font: { size: 11, weight: 'bold' } } }
          }
        }
      });
    }
  }

  function popup(p) {
    if (p.start_dong) {
      return `<strong>${esc(p.start_dong)} → ${esc(p.end_dong)}</strong><br>` +
        `<small>통행 ${Number(p.total_trips || 0).toLocaleString()}건 · 승객 ${Number(p.total_passengers || 0).toLocaleString()}명</small>` +
        `<br><small>평균 ${esc(p.avg_distance_km)}km / ${esc(p.avg_time_min)}분</small>`;
    }

    if (p.layer_type === "boundary" || p.admin_name || p.housing_district_name) {
      const name = p.housing_district_name || p.admin_name || p.name || "택지지구";
      let content = `<strong>${esc(name)}</strong>`;
      if (p.total_passengers !== undefined && p.total_passengers !== null) {
        content += `<br><small>총 이용량: <b>${Number(p.total_passengers).toLocaleString()}명</b></small>`;
      }
      if (p.total_stops !== undefined && p.total_stops !== null) {
        content += `<br><small>총 정류장 수: <b>${Number(p.total_stops).toLocaleString()}개</b></small>`;
      }
      return content;
    }

    let content = `<strong>${esc(p.stop_name || p.name)}</strong><br><small>${esc(p.dong_name || "")}</small>`;
    if (p.total_passengers !== undefined) {
      content += `<br>총 이용량: <b>${Number(p.total_passengers).toLocaleString()}명</b>`;
    }
    if (p.total_boardings !== undefined && p.total_alightings !== undefined) {
      content += `<br><small>(승차 ${Number(p.total_boardings).toLocaleString()} / 하차 ${Number(p.total_alightings).toLocaleString()})</small>`;
    }
    return content;
  }

  function showLegend(type, maxPassengers = 0, isSubway = false) {
    const legendEl = $("mapLegend");
    if (!legendEl) return;

    if (type === "top_stops" && maxPassengers > 0) {
      const p75 = Math.round(maxPassengers * 0.75).toLocaleString();
      const p50 = Math.round(maxPassengers * 0.5).toLocaleString();
      const p25 = Math.round(maxPassengers * 0.25).toLocaleString();

      const colors = isSubway 
        ? { c4: 'rgba(126, 34, 206, 0.82)', c3: 'rgba(220, 38, 38, 0.82)', c2: 'rgba(249, 115, 22, 0.82)', c1: 'rgba(234, 179, 8, 0.82)' }
        : { c4: 'rgba(88, 28, 135, 0.82)', c3: 'rgba(29, 78, 216, 0.82)', c2: 'rgba(2, 132, 199, 0.82)', c1: 'rgba(56, 189, 248, 0.82)' };

      legendEl.innerHTML = `
        <h4 style="margin-bottom:8px; font-weight:bold;">이용수요 단계 구분</h4>
        <div style="display: flex; flex-direction: column; gap: 6px; font-size: 12px; color: #f8fafc;">
          <div style="display:flex; align-items:center; gap:10px;">
            <span style="width:16px; height:16px; border-radius:50%; background:${colors.c4}; border:1.5px solid #fff; display:inline-block; flex-shrink:0;"></span>
            <span>매우 높음 (${p75}명 이상)</span>
          </div>
          <div style="display:flex; align-items:center; gap:10px;">
            <span style="width:14px; height:14px; border-radius:50%; background:${colors.c3}; border:1.5px solid #fff; display:inline-block; flex-shrink:0;"></span>
            <span>높음 (${p50} ~ ${p75}명)</span>
          </div>
          <div style="display:flex; align-items:center; gap:10px;">
            <span style="width:12px; height:12px; border-radius:50%; background:${colors.c2}; border:1.5px solid #fff; display:inline-block; flex-shrink:0;"></span>
            <span>보통 (${p25} ~ ${p50}명)</span>
          </div>
          <div style="display:flex; align-items:center; gap:10px;">
            <span style="width:10px; height:10px; border-radius:50%; background:${colors.c1}; border:1.5px solid #fff; display:inline-block; flex-shrink:0;"></span>
            <span>낮음 (${p25}명 미만)</span>
          </div>
        </div>
      `;
    } else {
      const labels = { 
        housing_district: "보라색 색상 농도는 택지지구별 이용수요 단계구분을 나타냅니다.", 
        od_flow: "초록색은 출발지, 빨간색은 도착지, 화살표 선은 통행 방향과 흐름입니다." 
      };
      legendEl.innerHTML = `<h4>지도 범례</h4><div class="legend-item">${labels[type] || "분석 결과"}</div>`;
    }
    legendEl.classList.add("active");
  }

  function render(geojson, queryType) {
    clearLayer();
    if (!geojson?.features?.length) return;

    const validFeatures = geojson.features.filter(f => {
      if (!f || !f.geometry || !Array.isArray(f.geometry.coordinates)) return false;
      const type = f.geometry.type;
      const coords = f.geometry.coordinates;
      if (type === "Point") return isValidCoord(coords);
      if (type === "LineString") return coords.every(isValidCoord);
      if (type === "Polygon" && coords[0]) return coords[0].every(isValidCoord);
      if (type === "MultiPolygon" && coords[0] && coords[0][0]) return coords[0][0].every(isValidCoord);
      return true;
    });

    if (validFeatures.length === 0) return;

    const sanitizedGeojson = { ...geojson, features: validFeatures };

    let maxPassengers = 0;
    let isSubwayData = false;
    sanitizedGeojson.features.forEach(f => {
      const p = f.properties || {};
      const count = Number(p.total_passengers || p.total_boardings || 0);
      if (count > maxPassengers) maxPassengers = count;
      if (p.is_subway || p.point_type === "subway") isSubwayData = true;
    });

    if (queryType === "od_flow") {
      try {
        const odLayer = createODLayer(sanitizedGeojson);
        analysisLayerGroup.addLayer(odLayer);
      } catch (e) {
        console.warn("OD 레이어 추가 오류:", e);
      }
    } 
    else {
      try {
        const resultGeoJsonLayer = L.geoJSON(sanitizedGeojson, {
          coordsToLatLng: function (coords) {
            let lng = Number(coords[0]), lat = Number(coords[1]);
            if (lng >= 30 && lng <= 45 && lat >= 120 && lat <= 135) return L.latLng(lng, lat);
            return L.latLng(lat, lng);
          },
          style: (feature) => {
            const p = feature.properties || {};
            const geomType = feature.geometry?.type;

            // 💡 [수정] dashArray를 완전한 빈 문자열("")로 설정하여 깔끔한 실선 보장
            if (geomType === "Polygon" || geomType === "MultiPolygon" || queryType === "housing_district" || p.layer_type === "housing_district" || p.layer_type === "housing_districts" || p.admin_level === "housing_district") {
              let fillOpacity = 0.2;
              if (p.total_passengers !== undefined && maxPassengers > 0) {
                const ratio = Math.min(Math.max(p.total_passengers / maxPassengers, 0), 1);
                fillOpacity = 0.15 + (ratio * 0.5);
              }
              return { 
                color: "#a855f7",      // 보라색
                weight: 3,             // 선 두께 3px
                dashArray: "",         // 확실한 실선 처리
                fill: true, 
                fillColor: "#a855f7", 
                fillOpacity: fillOpacity 
              };
            }

            if (p.layer_type === "boundary" || p.layer_type === "city_boundary") {
              return { color: "#f59e0b", weight: 2, dashArray: "4, 4", fill: false, fillOpacity: 0 };
            }

            if (p.layer_type === "od_line") {
              return { color: "#ef4444", weight: p.line_weight || 3.5, opacity: .85 };
            }

            return { color: "#a855f7", weight: 3, dashArray: "", fill: true, fillColor: "#a855f7", fillOpacity: 0.2 };
          },
          pointToLayer: (feature, latlng) => {
            if (!latlng || !Number.isFinite(latlng.lat) || !Number.isFinite(latlng.lng)) return null;
            
            const p = feature.properties || {};
            const count = Number(p.total_passengers || p.total_boardings || 0);
            const isSubway = p.is_subway || p.point_type === "subway";

            const style = getGraduatedStyle(count, maxPassengers, isSubway);
            const markerColor = p.point_type === "origin" ? "#16a34a" : p.point_type === "destination" ? "#dc2626" : (p.marker_color || style.color);
            const size = style.radius * 2;

            const customIcon = L.divIcon({
              className: "custom-station-marker",
              html: `<div style="
                background-color: ${markerColor};
                opacity: 0.82;
                width: ${size}px;
                height: ${size}px;
                border-radius: 50%;
                border: 2px solid #ffffff;
                box-shadow: 0 2px 6px rgba(0,0,0,0.35);
                cursor: pointer;
                transition: transform 0.15s ease;
              " title="${esc(p.stop_name || p.name || '')}"></div>`,
              iconSize: [size, size],
              iconAnchor: [style.radius, style.radius]
            });

            return L.marker(latlng, { icon: customIcon });
          },
          onEachFeature: (feature, layer) => {
            if (layer && typeof layer.bindPopup === 'function') {
              layer.bindPopup(popup(feature.properties || {}));
            }
          }
        });
        analysisLayerGroup.addLayer(resultGeoJsonLayer);
      } catch (e) {
        console.warn("지도 객체 생성 중 오류:", e);
      }
    }

    // 💡 [수정] 레이어 체인이 아니라 GeoJSON 좌표에서 직접 Bound를 계산하여 확실한 자동 줌인 적용
    setTimeout(() => {
      try {
        map.invalidateSize(); // 지도 사이즈 동기화
        const validBounds = computeBoundsFromGeoJSON(sanitizedGeojson);

        // 🔍 디버그 로그: 문제가 재발하면 브라우저 콘솔(F12)에서 이 로그를 확인
        console.log(
          "[줌투레이어] features:", sanitizedGeojson.features.length,
          "| bounds 유효:", validBounds.isValid(),
          validBounds.isValid() ? "| bbox: " + validBounds.toBBoxString() : ""
        );

        if (validBounds.isValid()) {
          map.fitBounds(validBounds, { padding: [50, 50], maxZoom: 15, animate: true });
        } else {
          console.warn("[줌투레이어] 유효한 좌표를 찾지 못해 확대를 건너뛰었습니다.");
        }
      } catch (e) {
        console.warn("자동 줌투레이어 에러:", e);
      }
    }, 150);

    showLegend(queryType, maxPassengers, isSubwayData);
  }

  // 💡 [수정] 기본 Reference Layer 의 택지지구 선 역시 보라색 실선으로 통일
  function referenceStyle(feature) {
    const type = feature.properties?.layer_type;
    if (type === "city_boundary") return { color: "#f59e0b", weight: 1.8, dashArray: "4, 6", fill: false, fillOpacity: 0 };
    if (type === "dong_boundary") return { color: "#38bdf8", weight: 1, fill: false, fillOpacity: 0 };
    if (type === "housing_district" || type === "housing_districts") return { color: "#a855f7", weight: 2.5, fill: false, fillOpacity: 0, dashArray: "" };
    return { color: "#94a3b8", weight: 1.5, fill: false, fillOpacity: 0, dashArray: "4, 4" };
  }

  function referencePoint(feature, latlng) {
    return L.circleMarker(latlng, { radius: 4, fillColor: "#38bdf8", color: "#ffffff", weight: 1, fillOpacity: 0.9 });
  }

  function curvedPath(start, end) {
    const dx = end.lng - start.lng;
    const dy = end.lat - start.lat;
    const control = L.latLng(
      (start.lat + end.lat) / 2 + dx * 0.2, 
      (start.lng + end.lng) / 2 - dy * 0.2
    );
    const points = [];
    for (let step = 0; step <= 30; step += 1) {
      const t = step / 30, inv = 1 - t;
      points.push(L.latLng(
        inv * inv * start.lat + 2 * inv * t * control.lat + t * t * end.lat, 
        inv * inv * start.lng + 2 * inv * t * control.lng + t * t * end.lng
      ));
    }
    return points;
  }

  function arrowIcon(before, end, color, weight) {
    const degrees = Math.atan2(end.lat - before.lat, end.lng - before.lng) * 180 / Math.PI;
    const size = Math.max(16, Math.min(weight * 2.5, 32));
    return L.divIcon({
      className: "od-arrow-icon",
      html: `<svg viewBox="0 0 32 32" aria-hidden="true" style="transform:rotate(${degrees}deg); width:${size}px; height:${size}px; display:block;">
               <path d="M4 5 L28 16 L4 27 L10 16 Z" fill="${color}" stroke="#ffffff" stroke-width="1.5"/>
             </svg>`,
      iconSize: [size, size],
      iconAnchor: [size / 2, size / 2],
    });
  }

  function createODLayer(geojson) {
    const group = L.featureGroup();
    geojson.features.forEach((feature) => {
      const p = feature.properties || {}, geometry = feature.geometry || {};
      
      if (geometry.type === "LineString" && Array.isArray(geometry.coordinates) && geometry.coordinates.length >= 2) {
        const startCoord = geometry.coordinates[0];
        const endCoord = geometry.coordinates[geometry.coordinates.length - 1];

        if (!isValidCoord(startCoord) || !isValidCoord(endCoord)) return;
        
        let startLng = Number(startCoord[0]), startLat = Number(startCoord[1]);
        if (startLng >= 30 && startLng <= 45 && startLat >= 120 && startLat <= 135) {
          const tmp = startLng; startLng = startLat; startLat = tmp;
        }

        let endLng = Number(endCoord[0]), endLat = Number(endCoord[1]);
        if (endLng >= 30 && endLng <= 45 && endLat >= 120 && endLat <= 135) {
          const tmp = endLng; endLng = endLat; endLat = tmp;
        }

        const start = L.latLng(startLat, startLng);
        const end = L.latLng(endLat, endLng);
        
        const path = curvedPath(start, end);
        const color = p.line_color || "#ef4444";
        const weight = p.line_weight || 3.5;
        const opacity = p.line_opacity || 0.85;

        const line = L.polyline(path, { color: color, weight: weight, opacity: opacity, lineCap: "round" }).bindPopup(popup(p));
        const arrow = L.marker(path[path.length - 1], { icon: arrowIcon(path[path.length - 2], path[path.length - 1], color, weight), interactive: false, zIndexOffset: 1000 });
        const originMarker = L.circleMarker(start, { radius: Math.max(4, weight * 0.8), fillColor: "#16a34a", color: "#fff", weight: 1, fillOpacity: 0.9 }).bindPopup(`<b>출발지: ${esc(p.start_dong || p.origin_name || '탄현지구')}</b>`);

        group.addLayer(line);
        group.addLayer(arrow);
        group.addLayer(originMarker);
      } 
      else if (p.layer_type === "od_point" && Array.isArray(geometry.coordinates) && isValidCoord(geometry.coordinates)) {
        let lng = Number(geometry.coordinates[0]), lat = Number(geometry.coordinates[1]);
        if (lng >= 30 && lng <= 45 && lat >= 120 && lat <= 135) { const tmp = lng; lng = lat; lat = tmp; }
        const color = p.point_type === "origin" ? "#16a34a" : "#dc2626";
        group.addLayer(L.circleMarker([lat, lng], { radius: 6, fillColor: color, color: "#fff", weight: 1, fillOpacity: 0.9 }).bindPopup(popup(p)));
      }
    });
    return group;
  }

  function addReferenceLayer(name, geojson) {
    try {
      const layer = name === "od_flows" ? createODLayer(geojson) : L.geoJSON(geojson, {
        style: referenceStyle,
        pointToLayer: referencePoint,
        onEachFeature: (feature, layerItem) => {
          if (layerItem && typeof layerItem.bindPopup === 'function') {
            const p = feature.properties || {};
            if (p.layer_type === "bus_route") layerItem.bindPopup(`<strong>${esc(p.route_name || p.route_id || "버스 노선")}</strong>`);
            else if (p.layer_type === "bus_stop") layerItem.bindPopup(`<strong>${esc(p.stop_name || "정류장")}</strong><br><small>${esc(p.stop_id || "")}</small>`);
            else layerItem.bindPopup(`<strong>${esc(p.admin_name || "행정구역")}</strong>`);
          }
        },
      });
      layer.addTo(map);
      const labels = { city_boundary: "고양시 경계", administrative_dong: "행정동", housing_districts: "택지지구", bus_routes: "버스 노선", bus_stops: "버스 정류장" };
      referenceLayers[labels[name] || name] = layer;
      layerControl.addOverlay(layer, labels[name] || name);
    } catch (e) {
      console.warn("레이어 추가 실패:", name, e);
    }
  }

  async function loadDefaultLayers() {
    try {
      const response = await fetch("/api/layers/default");
      if (!response.ok) throw new Error("레이어 조회 실패");
      const layers = await response.json();
      Object.entries(layers).forEach(([name, geojson]) => addReferenceLayer(name, geojson));
      const city = referenceLayers["고양시 경계"];
      if (city && city.getBounds && city.getBounds().isValid()) map.fitBounds(city.getBounds(), { padding: [24, 24] });
    } catch (error) {
      console.warn("기본 레이어를 불러오지 못했습니다.", error);
    }
  }

  function addMessage(text, role) {
    $("chatMessages").querySelector(".welcome-message")?.remove();
    const wrapper = document.createElement("div"); wrapper.className = `message ${role}`;
    const bubble = document.createElement("div"); bubble.className = "message-bubble";
    if (role === "ai") bubble.innerHTML = window.marked ? marked.parse(text) : esc(text).replaceAll("\n", "<br>"); else bubble.textContent = text;
    wrapper.append(bubble); $("chatMessages").append(wrapper); $("chatMessages").scrollTop = $("chatMessages").scrollHeight;
  }

  async function send(prompt) {
    if (!prompt || !prompt.trim()) return;
    addMessage(prompt, "user"); $("chatInput").value = ""; $("typingIndicator").classList.add("active"); $("sendBtn").disabled = true;
    try {
      const response = await fetch("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ prompt }) });
      const data = await response.json();
      addMessage(data.text || "응답을 만들지 못했습니다.", "ai"); 
      render(data.geojson, data.query_type);
      renderAnalyticsChart(data.chart_data);
      $("mapInfoTitle").textContent = "분석 결과"; $("mapInfoDetail").textContent = `${data.geojson?.features?.length || 0}개 지도 객체`; $("mapInfo").classList.add("active");
    } catch (error) { 
      console.error("클라이언트 처리 오류:", error);
      addMessage(`분석 결과 처리 오류: ${error.message}`, "ai"); 
    }
    finally { $("typingIndicator").classList.remove("active"); $("sendBtn").disabled = false; }
  }

  async function health() {
    try { const r = await fetch("/api/health"); const d = await r.json(); $("connectionStatus").textContent = d.detail; $("statusDot").style.background = d.ok ? "#48bb78" : "#fc8181"; } catch { $("connectionStatus").textContent = "서버 연결 안 됨"; }
  }

  $("sendBtn").addEventListener("click", () => send($("chatInput").value));
  $("chatInput").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); send(e.target.value); } });
  
  document.querySelectorAll(".quick-btn").forEach((b) => {
    b.addEventListener("click", () => {
      const promptText = b.getAttribute("data-prompt") || b.getAttribute("data-query") || b.textContent.trim();
      send(promptText);
    });
  });

  health();
  loadDefaultLayers();
})();