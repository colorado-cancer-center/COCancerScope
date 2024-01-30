"""
API endpoints that return statistics, e.g. cancer incidence/mortality,
or sociodemographic measures.
"""

import csv
from io import StringIO

from collections import defaultdict
from typing import Optional
from fastapi import Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from fastapi_pagination import Page
from fastapi_pagination.ext.sqlmodel import paginate

from tools.strings import slugify, slug_modelname_sans_type
from db import get_session

from settings import LIMIT_TO_STATE

from models import (
    STATS_MODELS,
    CANCER_MODELS,
    MEASURE_DESCRIPTIONS
)

from fastapi import APIRouter

router = APIRouter(prefix="/stats")


# ============================================================================
# === statistics routes
# ============================================================================

class FIPSValue(BaseModel):
    value: float
    aac: Optional[float]

class FIPSMeasureResponse(BaseModel):
    min: Optional[float]
    max: Optional[float]
    values: dict[str, FIPSValue]

# provides high-level information about the available categories and measures
# by iterating over the STATS_MODELS dict

class MeasuresMetaResponse(BaseModel):
    label: str

class CateogryMetaResponse(BaseModel):
    label: str
    measures: dict[str, MeasuresMetaResponse]

class StatsMetaResponse(BaseModel):
    label: str
    categories: dict[str, CateogryMetaResponse]

@router.get(f"/measures", response_model=dict[str, StatsMetaResponse])
async def get_measures(session: AsyncSession = Depends(get_session)):
    f"""
    Autogenerated method; gets all distinct values of 'measure' for all stats tables.
    """

    # stores measures by type (country vs. tract) and table
    all_measures = {}

    for type, models in STATS_MODELS.items():
        all_measures[type] = {
            "label": type.capitalize(),
            "categories": {}
        }

        for model in models:
            simple_model_name = slug_modelname_sans_type(model, type)

            if model in CANCER_MODELS:
                query = select(model.Site).distinct().order_by(model.Site)
            else:
                query = select(model.measure).distinct().order_by(model.measure)
            
            # if LIMIT_TO_STATE is not None:
            #     query = query.where(model.State == LIMIT_TO_STATE)

            result = await session.execute(query)

            all_measures[type]["categories"][simple_model_name] = {
                "label": model.Config.label or simple_model_name,
                "measures": {
                    x: {
                        "label": MEASURE_DESCRIPTIONS.get(simple_model_name, {}).get(x, x) or x,
                    }
                    for x in result.scalars().all()
                }
            }

    return all_measures


# generates a set of stats endpoints per model from the STATS_MODELS dict

for type, family in STATS_MODELS.items():
    for model in family:
        simple_model_name = slug_modelname_sans_type(model, type)

        # despite us iterating over 'model' in the loop, we need to use a closure to
        # capture the value of 'model' at the time of the loop iteration. in this
        # case, the closure is the "generate_routes" function below that closes
        # model as an argument.
        # otherwise the methods will use the most recent value of 'model', which
        # will always be the last model in the list.

        def generate_routes(type=type, model=model, simple_model_name=simple_model_name):
            @router.get(
                f"/{type}/{simple_model_name}/measures", 
                response_model=list[str],
                description=f"""
                Autogenerated method; gets all distinct values of 'measure' for the {model.__name__} table.
                """
            )
            async def get_dataset_measures(session: AsyncSession = Depends(get_session)):
                # check if model is a cancer model
                # if so, we need to use the "Site" column instead of "measure"
                if model in CANCER_MODELS:
                    query = select(model.Site).distinct().order_by(model.Site)
                else:
                    query = select(model.measure).distinct().order_by(model.measure)
                
                if LIMIT_TO_STATE is not None:
                    query = query.where(model.State == LIMIT_TO_STATE)

                result = await session.execute(query)
                objects = result.scalars().all()

                return objects

            @router.get(
                f"/{type}/{simple_model_name}",
                response_model=Page[model], 
                description=f"""
                Autogenerated method; gets all rows from the {model.__name__} table. Returns the results as a paginated list.
                """
            )
            async def get_dataset(
                measure: Optional[str] = None, session: AsyncSession = Depends(get_session)
            ):
                query = select(model)
                
                if LIMIT_TO_STATE is not None:
                    query = query.where(model.State == LIMIT_TO_STATE)

                if measure is not None:
                    query = query.where(model.measure == measure)

                result = await paginate(session, query)

                return result
            
            @router.get(
                f"/{type}/{simple_model_name}/fips-value",
                response_model=FIPSMeasureResponse,
                description=f"""
                Autogenerated method; gets pairings of FIPS (an ID that, in this case,
                specifies geographic regions) and the value of the given measure for that
                region.
                """
            )
            async def get_dataset_fips(
                measure: str, session: AsyncSession = Depends(get_session)
            ):
                print(f"Processing {model.__name__} for measure {measure}")

                if model not in CANCER_MODELS:
                    query = select((model.FIPS, model.value)).where(model.measure == measure)
                else:
                    query = select((model.FIPS, model.AAR.label("value"), model.AAC.label("aac"))).where(model.Site == measure)
                
                if LIMIT_TO_STATE is not None:
                    query = query.where(model.State == LIMIT_TO_STATE)

                # compute mins and maxes so we can build a color scale
                # # if it's a cancer endpint, we need to use the "Site" column instead of "measure", and "AAR" instead of "value
                if model not in CANCER_MODELS:
                    stats_query = select(func.min(model.value), func.max(model.value)).where(model.measure == measure)
                else:
                    stats_query = select(func.min(model.AAR), func.max(model.AAR)).where(model.Site == measure)
                
                stats_result = await session.execute(stats_query)
                stats = stats_result.all()[0]

                result = await session.execute(query)
                objects = result.all()

                # for non-cancer models, return a dict of FIPS and values
                # for cancer models, return a dict of FIPS and a sub-dict of AAR and AAC values
                if model not in CANCER_MODELS:
                    values = {x["FIPS"]: {"value": x["value"]} for x in objects}
                else:
                    values = {x["FIPS"]: {"value": x["value"], "aac": x["aac"]} for x in objects}

                return FIPSMeasureResponse(
                    min=stats[0],
                    max=stats[1],
                    values=values
                )

            @router.get(
                f"/{type}/{simple_model_name}/as-csv",
                response_class=StreamingResponse,
                description=f"""
                Autogenerated method; download {type}-level {simple_model_name} data for a given measure, if provided, as a CSV.
                """
            )
            async def download_dataset(
                measure: Optional[str] = None,
                session: AsyncSession = Depends(get_session)
            ):
                # get human labels for measures within this model, if available
                model_measure_labels = MEASURE_DESCRIPTIONS.get(simple_model_name, {})

                def label_for_measure(measure):
                    return model_measure_labels.get(measure, measure) or measure

                if measure is not None:
                    measure_label = label_for_measure(measure)
                    print(f"Downloading {model.__name__} ({simple_model_name}) for measure {measure} ({measure_label})")
                else:
                    print(f"Downloading {model.__name__} ({simple_model_name}) for all measure")

                if model not in CANCER_MODELS:
                    query = select(
                        (model.FIPS.label("GEOID"), model.County, model.State, model.measure, model.value)
                    )

                    if measure is not None:
                        query = query.where(model.measure == measure)

                else:
                    query = select(
                        (model.FIPS.label("GEOID"), model.County, model.State, model.Site.label("measure"), model.AAR.label("value"))
                    )
                    
                    if measure is not None:
                        query = query.where(model.Site == measure)
                
                if LIMIT_TO_STATE is not None:
                    query = query.where(model.State == LIMIT_TO_STATE)

                result = await session.execute(query)
                objects = result.all()

                with StringIO() as fp:
                    writer = csv.writer(fp)
                    writer.writerow(["GEOID", "County", "State", "measure", "value"])
                    writer.writerows(
                        [
                            x["GEOID"],
                            x["County"],
                            x["State"],
                            label_for_measure(x["measure"]),
                            x["value"],
                        ] for x in objects
                    )

                    response = StreamingResponse(iter([fp.getvalue()]), media_type="text/csv")
                    response.headers["Content-Disposition"] = f"attachment; filename=COE_{slugify(measure or simple_model_name)}_{type}.csv"

                    return response
            
        generate_routes()
