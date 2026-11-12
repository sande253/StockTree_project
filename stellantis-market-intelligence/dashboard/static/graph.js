// Ecosystem Graph - Bloomberg-terminal style force network, Stellantis fixed at the centre.
// Built with D3 v7 (loaded via CDN in ecosystem_graph.html). No build step, vanilla JS only.
(function () {
  const svg = d3.select("#ecosystem-graph");
  const stage = document.querySelector(".graph-stage-body");
  const tooltip = document.getElementById("graph-tooltip");
  if (svg.empty() || !stage || typeof NETWORK === "undefined") return;

  const CENTER_ID = "STLA";

  const TYPE_COLORS = {
    brand: "#ffb000",
    supplier: "#00d4ff",
    battery_supplier: "#14f1b2",
    semiconductor_supplier: "#4da3ff",
    software_partner: "#c792ea",
    cloud_partner: "#80d8ff",
    technology_partner: "#9d7bff",
    logistics_partner: "#c6ff00",
    manufacturing_partner: "#ff9142",
    joint_venture: "#ff6fb0",
    customer: "#39ff14",
    partner: "#ffd60a",
    competitor: "#ff4136",
    default: "#9aa0a6",
  };

  function colorFor(type) {
    return TYPE_COLORS[type] || TYPE_COLORS.default;
  }

  // Tint the legend / filter swatches that are plain markup (color decided here, not in Jinja).
  document.querySelectorAll(".type-dot").forEach((el) => {
    const type = el.getAttribute("data-type");
    const color = el.hasAttribute("data-center") ? "#ffb000" : colorFor(type);
    el.style.background = color;
    el.style.color = color; // feeds `box-shadow: 0 0 6px currentColor`
  });

  // One-time keyframes for the centre node's radar pulse (SVG + CSS animation).
  if (!document.getElementById("graph-radar-style")) {
    const style = document.createElement("style");
    style.id = "graph-radar-style";
    style.textContent = `
      @keyframes radarPulse {
        0% { r: 36px; opacity: 0.55; }
        100% { r: 95px; opacity: 0; }
      }
      .radar-ring { animation: radarPulse 2.4s ease-out infinite; transform-origin: center; }
      .radar-ring.delay { animation-delay: 1.2s; }
      .link-flow { stroke-dasharray: 3 5; }
    `;
    document.head.appendChild(style);
  }

  const nodesRaw = NETWORK.nodes || [];
  const edgesRaw = NETWORK.edges || [];

  // Assign each relationship type a concentric ring distance from STLA, in first-seen order.
  const typesInOrder = (typeof RELATIONSHIP_TYPES !== "undefined" && RELATIONSHIP_TYPES.length)
    ? RELATIONSHIP_TYPES
    : Array.from(new Set(edgesRaw.map((e) => e.relationship_type).filter(Boolean)));
  const ringFor = {};
  typesInOrder.forEach((t, i) => { ringFor[t] = i; });

  const edgeTypeByTarget = {};
  edgesRaw.forEach((e) => { edgeTypeByTarget[e.target] = e.relationship_type; });

  const nodes = nodesRaw.map((n) => {
    const isCenter = n.id === CENTER_ID;
    const relType = edgeTypeByTarget[n.id] || "default";
    const ringIndex = ringFor[relType] !== undefined ? ringFor[relType] : 0;
    const fullName = n.company_name || n.name || n.id;
    return {
      ...n,
      isCenter,
      relType,
      fullName,
      ringRadius: 130 + ringIndex * 95,
      r: isCenter ? 34 : 15,
    };
  });

  const links = edgesRaw
    .filter((e) => e.source && e.target)
    .map((e) => ({ ...e }));

  // ---- SVG scaffolding -----------------------------------------------------------------
  let width = stage.clientWidth || 900;
  let height = stage.clientHeight || 600;
  svg.attr("viewBox", `0 0 ${width} ${height}`).attr("preserveAspectRatio", "xMidYMid meet");

  const viewport = svg.append("g").attr("class", "viewport");
  const ringsLayer = viewport.append("g").attr("class", "rings");
  const linksLayer = viewport.append("g").attr("class", "links");
  const nodesLayer = viewport.append("g").attr("class", "nodes-layer");

  const zoom = d3.zoom()
    .scaleExtent([0.3, 4])
    .on("zoom", (event) => viewport.attr("transform", event.transform));
  svg.call(zoom);

  const cx = () => width / 2;
  const cy = () => height / 2;

  function drawRings() {
    ringsLayer.selectAll("circle").remove();
    typesInOrder.forEach((t, i) => {
      ringsLayer.append("circle")
        .attr("cx", cx())
        .attr("cy", cy())
        .attr("r", 130 + i * 95)
        .attr("fill", "none")
        .attr("stroke", colorFor(t))
        .attr("stroke-opacity", 0.12)
        .attr("stroke-dasharray", "2,6");
    });
  }
  drawRings();

  // ---- Force simulation -----------------------------------------------------------------
  const simulation = d3.forceSimulation(nodes)
    .force("link", d3.forceLink(links).id((d) => d.id).distance((d) => 70 + (d.confidence === "high" ? -10 : 20)).strength(0.35))
    .force("charge", d3.forceManyBody().strength((d) => (d.isCenter ? -40 : -220)))
    .force("collide", d3.forceCollide().radius((d) => d.r + 26).iterations(2))
    .force("radial", d3.forceRadial((d) => (d.isCenter ? 0 : d.ringRadius), cx(), cy()).strength((d) => (d.isCenter ? 1 : 0.85)))
    .on("tick", ticked);

  const centerNode = nodes.find((n) => n.isCenter);
  if (centerNode) {
    centerNode.fx = cx();
    centerNode.fy = cy();
  }

  // ---- Links ----------------------------------------------------------------------------
  const linkSel = linksLayer.selectAll("path.link")
    .data(links)
    .join("path")
    .attr("class", "link link-flow")
    .attr("stroke", (d) => colorFor(d.relationship_type))
    .attr("stroke-width", (d) => (d.confidence === "high" ? 2.4 : d.confidence === "low" ? 1.2 : 1.8))
    .attr("stroke-opacity", 0.55)
    .on("mouseenter", function (event, d) {
      d3.select(this).attr("stroke-opacity", 1).attr("stroke-width", 3.5);
      const srcLabel = (d.source.fullName || d.source.id || d.source);
      const tgtLabel = (d.target.fullName || d.target.id || d.target);
      const reason = d.description || d.business_area || "No documented reason on file";
      showTooltip(event, `
        <strong style="color:${colorFor(d.relationship_type)}">${srcLabel} &rarr; ${tgtLabel}</strong>
        HOW: ${(d.relationship_type || "unknown").replace(/_/g, " ").toUpperCase()}<br>
        WHY: ${reason}<br>
        CONFIDENCE: ${d.confidence || "n/a"}
      `);
    })
    .on("mousemove", (event) => moveTooltip(event))
    .on("mouseleave", function () {
      d3.select(this).attr("stroke-opacity", 0.55).attr("stroke-width", (d) => (d.confidence === "high" ? 2.4 : d.confidence === "low" ? 1.2 : 1.8));
      hideTooltip();
    })
    .on("click", (event, d) => inspectEdge(d));

  // Animate the dash offset so edges visually "flow" evidence toward the centre.
  d3.timer(() => {
    linkSel.attr("stroke-dashoffset", (d, i) => -((Date.now() / 40 + i * 7) % 1000));
  });

  // ---- Nodes ----------------------------------------------------------------------------
  const nodeSel = nodesLayer.selectAll("g.node")
    .data(nodes)
    .join("g")
    .attr("class", "node")
    .call(drag(simulation));

  nodeSel.filter((d) => d.isCenter).each(function () {
    const g = d3.select(this);
    g.append("circle").attr("class", "radar-ring").attr("r", 36).attr("fill", "none").attr("stroke", "#ffb000").attr("stroke-width", 2);
    g.append("circle").attr("class", "radar-ring delay").attr("r", 36).attr("fill", "none").attr("stroke", "#ffb000").attr("stroke-width", 2);
  });

  nodeSel.append("circle")
    .attr("r", (d) => d.r)
    .attr("fill", (d) => (d.isCenter ? "#050505" : "#0f0f0f"))
    .attr("stroke", (d) => (d.isCenter ? "#ffb000" : colorFor(d.relType)))
    .attr("stroke-width", (d) => (d.isCenter ? 3.5 : 2.2));

  function truncateLabel(text, max) {
    if (!text) return "";
    return text.length > max ? `${text.slice(0, max - 1)}\u2026` : text;
  }

  nodeSel.append("text")
    .text((d) => truncateLabel(d.fullName, d.isCenter ? 28 : 20))
    .attr("text-anchor", "middle")
    .attr("y", (d) => d.r + 16)
    .attr("font-size", (d) => (d.isCenter ? 14 : 11))
    .attr("fill", (d) => (d.isCenter ? "#ffb000" : "#d8d8d8"));

  nodeSel.filter((d) => !d.isCenter).append("text")
    .text((d) => d.id)
    .attr("text-anchor", "middle")
    .attr("y", (d) => d.r + 29)
    .attr("font-size", 9)
    .attr("fill", "#6b7078")
    .attr("letter-spacing", "0.5px");

  nodeSel
    .on("mouseenter", function (event, d) {
      d3.select(this).select("circle").attr("filter", "brightness(1.3)");
      showTooltip(event, `
        <strong style="color:${d.isCenter ? "#ffb000" : colorFor(d.relType)}">${d.fullName}</strong>
        TICKER: ${d.id}<br>
        TYPE: ${(d.entity_type || "company").toUpperCase()}${d.isCenter ? " (PRIMARY)" : ""}
      `);
    })
    .on("mousemove", (event) => moveTooltip(event))
    .on("mouseleave", function () {
      d3.select(this).select("circle").attr("filter", null);
      hideTooltip();
    })
    .on("click", (event, d) => inspectNode(d));

  function ticked() {
    linkSel.attr("d", (d) => {
      const sx = d.source.x, sy = d.source.y, tx = d.target.x, ty = d.target.y;
      const dx = tx - sx, dy = ty - sy;
      const mx = sx + dx / 2 + dy / 10;
      const my = sy + dy / 2 - dx / 10;
      return `M${sx},${sy} Q${mx},${my} ${tx},${ty}`;
    });
    nodeSel.attr("transform", (d) => `translate(${d.x},${d.y})`);
  }

  // ---- Drag behaviour (centre node stays pinned) -----------------------------------------
  function drag(sim) {
    function started(event, d) {
      if (d.isCenter) return;
      if (!event.active) sim.alphaTarget(0.25).restart();
      d.fx = d.x;
      d.fy = d.y;
    }
    function dragged(event, d) {
      if (d.isCenter) return;
      d.fx = event.x;
      d.fy = event.y;
    }
    function ended(event, d) {
      if (d.isCenter) return;
      if (!event.active) sim.alphaTarget(0);
    }
    return d3.drag().on("start", started).on("drag", dragged).on("end", ended);
  }

  // ---- Tooltip --------------------------------------------------------------------------
  function showTooltip(event, html) {
    tooltip.innerHTML = html;
    tooltip.hidden = false;
    moveTooltip(event);
  }
  function moveTooltip(event) {
    const bounds = stage.getBoundingClientRect();
    tooltip.style.left = event.clientX - bounds.left + 16 + "px";
    tooltip.style.top = event.clientY - bounds.top + 16 + "px";
  }
  function hideTooltip() {
    tooltip.hidden = true;
  }

  // ---- Inspector panel --------------------------------------------------------------------
  const inspectorBody = document.getElementById("inspector-body");
  const inspectorTag = document.getElementById("inspector-tag");

  function row(key, value) {
    if (value === undefined || value === null || value === "") return "";
    return `<div class="term-row"><span class="term-key">${key}</span><span class="term-val">${value}</span></div>`;
  }

  function inspectNode(d) {
    inspectorTag.textContent = d.fullName || d.id;
    const related = links.filter((l) => (l.source.id || l.source) === d.id || (l.target.id || l.target) === d.id);
    let html = row("COMPANY", d.fullName || d.name || d.id) + row("TICKER", d.id) + row("TYPE", d.entity_type || "company");
    if (!d.isCenter) {
      html += row("LINKED EDGES", related.length);
    }
    related.slice(0, 8).forEach((l) => {
      const other = (l.source.id || l.source) === d.id ? l.target : l.source;
      const otherLabel = (other && (other.fullName || other.id)) || other;
      const why = l.description || l.business_area || "";
      html += `<div class="term-row"><span class="term-key">${(l.relationship_type || "edge").toUpperCase()}</span><span class="term-val">${otherLabel}${why ? ` &mdash; ${why}` : ""}</span></div>`;
    });
    inspectorBody.innerHTML = html || '<p class="muted">No additional data.</p>';
  }

  function inspectEdge(d) {
    const sourceLabel = d.source.fullName || d.source.id || d.source;
    const targetLabel = d.target.fullName || d.target.id || d.target;
    inspectorTag.textContent = `${sourceLabel} -> ${targetLabel}`;
    let html = "";
    html += row("HOW RELATED", d.relationship_type ? d.relationship_type.replace(/_/g, " ").toUpperCase() : null);
    html += row("WHY RELATED", d.description || d.business_area);
    html += row("CONFIDENCE", d.confidence);
    html += row("GEOGRAPHIC EXPOSURE", d.geographic_exposure);
    html += row("TICKER", d.target_entity_ticker);
    html += row("SOURCE", d.evidence_source);
    if (d.evidence_url) {
      html += `<div class="term-row"><span class="term-key">EVIDENCE</span><span class="term-val"><a class="term-link" href="${d.evidence_url}" target="_blank" rel="noopener noreferrer">open source &#8599;</a></span></div>`;
    }
    inspectorBody.innerHTML = html || '<p class="muted">No additional data.</p>';
  }

  // ---- Type filters (dim rather than hide, terminal-style) ------------------------------
  const searchInput = document.getElementById("node-search");

  function applyFilters() {
    const checked = new Set(
      Array.from(document.querySelectorAll(".rt-filter:checked")).map((c) => c.value)
    );
    const term = (searchInput && searchInput.value || "").trim().toLowerCase();

    linkSel.attr("stroke-opacity", (d) => (checked.has(d.relationship_type) ? 0.55 : 0.06));

    nodeSel.attr("opacity", (d) => {
      if (d.isCenter) return 1;
      const typeOk = checked.has(d.relType);
      const searchOk = !term || (d.name || d.id || "").toLowerCase().includes(term);
      return typeOk && searchOk ? 1 : 0.12;
    });
  }

  document.querySelectorAll(".rt-filter").forEach((cb) => cb.addEventListener("change", applyFilters));
  if (searchInput) searchInput.addEventListener("input", applyFilters);

  // ---- Reset view -------------------------------------------------------------------------
  const resetBtn = document.getElementById("reset-view");
  if (resetBtn) {
    resetBtn.addEventListener("click", () => {
      svg.transition().duration(400).call(zoom.transform, d3.zoomIdentity);
      nodes.forEach((n) => { if (!n.isCenter) { n.fx = null; n.fy = null; } });
      simulation.alpha(0.6).restart();
    });
  }

  // ---- Responsive resize ------------------------------------------------------------------
  window.addEventListener("resize", () => {
    width = stage.clientWidth || width;
    height = stage.clientHeight || height;
    svg.attr("viewBox", `0 0 ${width} ${height}`);
    if (centerNode) {
      centerNode.fx = cx();
      centerNode.fy = cy();
    }
    simulation.force("radial").x(cx()).y(cy());
    drawRings();
    simulation.alpha(0.3).restart();
  });

  // Default inspector view: STLA overview.
  if (centerNode) inspectNode(centerNode);
})();
