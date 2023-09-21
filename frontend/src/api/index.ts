import type { Feature, Geometry as GeoJsonGeometry } from "geojson";
import { mapValues } from "lodash";

// api root
const api = import.meta.env.VITE_API;

console.info("API:", api);

// request cache
const cache = new Map();

// general request
export async function request<T>(url: string) {
  // construct request
  const request = new Request(url);
  // unique request id for caching
  const id = JSON.stringify(request, ["url", "method", "headers"]);
  // get response from cache or make new request
  const response = cache.get(id) || (await fetch(request));
  // check status code
  if (!response.ok) throw Error("Response not OK");
  // parse response
  const parsed = await response.clone().json();
  // set cache for next time
  if (request.method === "GET") cache.set(id, response);
  return parsed as T;
}

// response from counties/tract api endpoints
type _Geometry = {
  [key: string]: string | number | undefined;

  full?: string;
  name?: string;
  fips?: string;
  us_fips?: string;
  objectid: number;
  ogc_fid: number;
  wkb_geometry: string;
}[];

// get geojson from geography data
export async function getGeometry(type: string, idField: string) {
  const data = await request<_Geometry>(`${api}/${type}`);

  // transform data into desired format
  return data.map(
    ({ wkb_geometry, ...d }) =>
      ({
        type: "Feature",
        geometry: JSON.parse(wkb_geometry) as GeoJsonGeometry,
        properties: {
          ...d,
          id: d[idField],
          name: d.full || d.name || "",
        },
      }) satisfies Feature,
  );
}

export type Geometry = Awaited<ReturnType<typeof getGeometry>>;

// response from facets api endpoint
type _Facets = {
  [key: string]: {
    label: string;
    categories: {
      [key: string]: {
        label: string;
        measures: {
          [key: string]: {
            label: string;
          };
        };
      };
    };
  };
};

// specific "level" of data
export type Facet = {
  [key: string]: {
    id: string;
    label: string;
    list?: Facet;
  };
};

// get hierarchical list of geographic levels, measure categories, and measures
export async function getFacets() {
  const data = await request<_Facets>(`${api}/stats/measures`);

  // transform data into desired format
  return mapValues(data, ({ label, categories }, key) => ({
    // geographic level
    id: key,
    label,
    list: mapValues(categories, ({ label, measures }, key) => ({
      // measure category
      id: key,
      label,
      list: mapValues(measures, ({ label }, key) => ({
        // measure
        id: key,
        label,
      })),
    })),
  })) satisfies Facet;
}

export type Facets = Awaited<ReturnType<typeof getFacets>>;

// response from values api endpoint
type _Values = {
  // range of values for specified measure
  max: number;
  min: number;
  // map of feature id to measure value
  values: { [key: number]: number };
};

// get values data for map
export async function getValues(
  level: string,
  category: string,
  measure: string,
) {
  const params = new URLSearchParams({ measure });
  const data = await request<_Values>(
    `${api}/stats/${level}/${category}/fips-value?` + params,
  );
  return data;
}

export type Values = Awaited<ReturnType<typeof getValues>>;
