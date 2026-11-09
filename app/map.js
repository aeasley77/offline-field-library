import * as maplibregl from '/app/map-assets/maplibre-gl.mjs';

const locations={
  albemarle:{center:[-80.200,35.350],zoom:11},
  harrisburg:{center:[-80.652,35.324],zoom:12},
  charlotte:{center:[-80.843,35.227],zoom:11}
};
const statusLine=document.querySelector('#map-status');
const errorBox=document.querySelector('#map-error');
const coordinates=document.querySelector('#coordinates');
const archiveUrl=new URL('/content/maps/charlotte-region.pmtiles',location.origin).href;

function showError(message){
  errorBox.hidden=false;
  errorBox.textContent=message;
  statusLine.textContent='Map data unavailable';
  document.querySelector('.live-dot').style.background='#d17c55';
}

async function loadMap(){
  if(!window.pmtiles||!window.basemaps){showError('The bundled offline map libraries could not be loaded. Restart the library and check that app/map-assets is present.');return;}
  try{
    const protocol=new pmtiles.Protocol();
    maplibregl.addProtocol('pmtiles',protocol.tile);
    const archive=new pmtiles.PMTiles(archiveUrl);
    protocol.add(archive);
    const header=await archive.getHeader();
    const style={
      version:8,
      glyphs:`${location.origin}/app/map-assets/fonts/{fontstack}/{range}.pbf`,
      sprite:`${location.origin}/app/map-assets/sprites/v4/light`,
      sources:{
        protomaps:{
          type:'vector',
          url:`pmtiles://${archiveUrl}`,
          attribution:'© OpenStreetMap contributors · ODbL'
        }
      },
      layers:basemaps.layers('protomaps',basemaps.namedFlavor('light'),{lang:'en'})
    };
    const map=new maplibregl.Map({
      container:'map',style,
      center:[header.centerLon,header.centerLat],
      zoom:8.2,
      minZoom:4,
      maxZoom:14,
      maxBounds:[[header.minLon-0.35,header.minLat-0.25],[header.maxLon+0.35,header.maxLat+0.25]],
      attributionControl:false,
      cooperativeGestures:true
    });
    map.addControl(new maplibregl.NavigationControl({showCompass:true}),'top-right');
    map.addControl(new maplibregl.ScaleControl({maxWidth:130,unit:'imperial'}),'bottom-left');
    map.addControl(new maplibregl.AttributionControl({compact:true,customAttribution:'<a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap ODbL</a> · Protomaps'}),'bottom-right');
    map.on('load',()=>{statusLine.textContent='Offline map ready · 07 Nov 2026';errorBox.hidden=true;});
    map.on('error',event=>{
      if(event?.error?.message)console.warn('Offline map request:',event.error.message);
    });
    map.on('click',event=>{
      const lng=event.lngLat.lng.toFixed(5),lat=event.lngLat.lat.toFixed(5);
      coordinates.textContent=`${lat}° N · ${lng}° W · Z${map.getZoom().toFixed(1)}`;
    });
    document.querySelectorAll('[data-center]').forEach(button=>button.addEventListener('click',()=>{
      const target=locations[button.dataset.center];
      if(target)map.flyTo({center:target.center,zoom:target.zoom,duration:700});
    }));
  }catch(error){
    console.error(error);
    showError('The regional tile archive could not be opened. Check that content/maps/charlotte-region.pmtiles is present and the dashboard server has restarted.');
  }
}

async function loadSheets(){
  const list=document.querySelector('#sheet-list');
  try{
    const categories=await(await fetch('/api/categories')).json();
    const maps=categories.find(category=>category.slug==='maps');
    const sheets=(maps?.items||[]).filter(item=>item.ext==='.pdf');
    const draw=filter=>{
      const matches=sheets.filter(item=>item.name.toLowerCase().includes(filter));
      list.innerHTML=matches.length?matches.map(item=>`<a href="/content/${item.path.split('/').map(encodeURIComponent).join('/')}" target="_blank" rel="noopener">${item.name}<small>PDF · ${(item.size/1048576).toFixed(1)} MB</small></a>`).join(''):'<p class="sheet-empty">No local map sheets match that filter.</p>';
    };
    draw('');
    document.querySelector('#sheet-filter').addEventListener('input',event=>draw(event.target.value.trim().toLowerCase()));
  }catch{list.innerHTML='<p class="sheet-empty">Could not load the local map sheet list.</p>';}
}

loadSheets();
loadMap();
