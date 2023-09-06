import L from 'leaflet';

import '@/styles/leafletLegend.scss'

export default function legend(options: any) {
  const legendControl = new L.Control({ position: 'bottomleft' });

  legendControl.onAdd = function(map) {
    if (!options.legendData?.rows) {
      const div = L.DomUtil.create('div');
      div.innerHTML = "No legend available";
      return div;
    }

    const data = options.legendData;
    const div = L.DomUtil.create('div', 'leaflet-map-legend');

    div.innerHTML = (
      (data.title ? `<div class="legend-header legend-title">${data.title}</div>\n` : '')+
      (data.subtitle ? `<div class="legend-header legend-subtitle">${data.subtitle}</div>\n` : '') +
      data.rows.map((row: any) => 
        `<div class="legend-row">
          <i class="legend-chip" style="background: ${row.color};"></i> <span class="legend-label">${row.label}</span>
        </div>`
      ).join('\n')
    )

    return div;
  };

  return legendControl;
}
