"""
API endpoints that return statistics, e.g. cancer incidence/mortality,
or sociodemographic measures.
"""

import csv
from io import StringIO

from typing import Optional, Annotated
from fastapi import Depends, Query, HTTPException, APIRouter
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
    MEASURE_DESCRIPTIONS,
    FACTOR_DESCRIPTIONS
)


router = APIRouter(prefix="/stats")


# ============================================================================
# === statistics routes
# ============================================================================

# ----------------------------------------------------------------
# --- general info routes
# ----------------------------------------------------------------

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

class FactorMetaResponse(BaseModel):
    label : str
    default : str | None
    values : dict[str, str]

class CateogryMetaResponse(BaseModel):
    label: str
    measures: dict[str, MeasuresMetaResponse]
    factors: Optional[dict[str, FactorMetaResponse]]

class StatsMetaResponse(BaseModel):
    label: str
    categories: dict[str, CateogryMetaResponse]

@router.get(f"/measures", response_model=dict[str, StatsMetaResponse])
async def get_measures(session: AsyncSession = Depends(get_session)):
    f"""
    Autogenerated method; gets all distinct values of 'measure' for all stats tables.

    If FACTOR_DESCRIPTIONS[model] exists, gets labels and distinct values
    for each factor.
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

            measure_descs = MEASURE_DESCRIPTIONS.get(simple_model_name, {})
            factor_descs = FACTOR_DESCRIPTIONS.get(simple_model_name, {})

            if model in CANCER_MODELS:
                query = select(model.Site).distinct().order_by(model.Site)
            else:
                query = select(model.measure).distinct().order_by(model.measure)

            # also put together queries for the values of factors
            factor_queries = {
                factor: {
                    'query': select(getattr(model, factor).distinct()),
                    'result': None
                }
                for factor in factor_descs
            }
            
            # if LIMIT_TO_STATE is not None:
            #     query = query.where(model.State == LIMIT_TO_STATE)

            # perform all our queries
            result = await session.execute(query)

            for factor, v in factor_queries.items():
                factor_queries[factor]['result'] = await session.execute(v["query"])

            all_measures[type]["categories"][simple_model_name] = {
                "label": model.Config.label or simple_model_name,
                "measures": {
                    x: {
                        "label": measure_descs.get(x, x) or x,
                    }
                    for x in result.scalars().all()
                },
                "factors": {
                    f: {
                        "label": str(fv["label"] or f),
                        "default": fv.get("default"),
                        "values": {
                            x: fv.get("values", {}).get(x, x) or x
                            for x in factor_queries[f]["result"].scalars().all()
                        }
                    }
                    for f, fv in factor_descs.items()
                }
            }

    return all_measures


# ----------------------------------------------------------------
# --- model-specific routes
# ----------------------------------------------------------------

# generates a set of stats endpoints per model from the STATS_MODELS dict

def parse_filter_str(filters):
    """
    Takes a string of the form "<factor1>:<value1>;<factor2>:<value2>;..." and
    returns a dict of factor-value pairs. Removes trailing whitespace on either
    end of the factor or value.

    >>> parse_filter_str("RE:White;Sex:Female")
    {"RE":"White","Sex":"Female"}
    >>> parse_filter_str("RE:  White NH  ; Sex: Female  ")
    {"RE":"White NH","Sex":"Female"}
    """
    return dict(
        tuple(z.strip() for z in x.split(":", maxsplit=2))
        for x in filters.split(";")
    )

class FactorsFilter(BaseModel):
    factors : dict[str,str]

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
                Autogenerated method; gets pairings of FIPS (an ID that, in this
                case, specifies geographic regions) and the value of the given
                measure for that region. If the given model has associated
                factors, then values for those factors can be provided through
                the 'filters' argument. The 'filters' argument takes a
                semicolon-delimited string of factor:value pairs, each delimited
                by a colon. For example, "RE:White NH;Sex:Female" is parsed into
                two filters, RE="White NH" and Sex="Female".
                """
            )
            async def get_dataset_fips(
                measure: str,
                # filter: Optional[FactorsFilter] = json_param(
                #     "filter", FactorsFilter,
                #     description="A set of factor/value pairs on which to filter"
                # ),
                filters : Annotated[
                    str | None, Query(regex="^([^:]+:[^:;]+;)*([^:]+:[^:;]+)$"),
                ] = None,
                session: AsyncSession = Depends(get_session)
            ):
                print(f"Processing {model.__name__} for measure {measure}")

                if model not in CANCER_MODELS:
                    query = select((model.FIPS, model.value)).where(model.measure == measure)
                else:
                    query = select((model.FIPS, model.AAR.label("value"), model.AAC.label("aac"))).where(model.Site == measure)
                
                # apply factor fields to the query, if the model has factors defined
                factor_labels = FACTOR_DESCRIPTIONS.get(simple_model_name, None)

                # takes a string of the form "<factor1>:<value1>;<factor2>:<value2>;..."
                # and produces a dict of factor-value pairs on which to filter
                # (unless filters wasn't specified, in which case don't apply any filters)
                filter_factors = parse_filter_str(filters) if filters is not None else {}

                if factor_labels:
                    for f, fv in factor_labels.items():
                        # filter each column of the model identified by the current
                        # factor, either to the supplied value, its default if available,
                        # or 'None'
                        query = query.where(
                            getattr(model, f) == (
                                filter_factors.get(f, fv.get("default", None))
                            )
                        )
                elif filters is not None:
                    # FIXME: should we throw an error, as we do here, or should we just ignore unused params?
                    raise HTTPException(
                        status_code=400,
                        detail=f"The 'filters' argument was specified, but the model '{simple_model_name}' has no defined factors"
                    )

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
                # get factors associated with this model, if any
                # (they'll be added as columns to the output)
                factor_labels = FACTOR_DESCRIPTIONS.get(simple_model_name, None)

                def label_for_measure(measure):
                    return model_measure_labels.get(measure, measure) or measure

                def model_to_fields(x, factor_labels):
                    fields = [
                        x["GEOID"],
                        x["County"],
                        x["State"],
                        label_for_measure(x["measure"]),
                        x["value"],
                    ]

                    if factor_labels is not None:
                        fields += [x[f] for f in factor_labels.keys()]

                    return fields

                if model not in CANCER_MODELS:
                    query = select(
                        (model.FIPS.label("GEOID"), model.County, model.State, model.measure, model.value)
                    )

                    if measure is not None:
                        query = query.where(model.measure == measure)

                else:
                    query = select(
                        (model.FIPS.label("GEOID"), model.County, model.State, model.Site.label("measure"), model.AAR.label("value"), model.RE, model.Sex)
                    )
                    
                    if measure is not None:
                        query = query.where(model.Site == measure)
                
                if LIMIT_TO_STATE is not None:
                    query = query.where(model.State == LIMIT_TO_STATE)

                result = await session.execute(query)
                objects = result.all()

                with StringIO() as fp:
                    writer = csv.writer(fp)

                    header_cols = ["GEOID", "County", "State", "measure", "value"]

                    if factor_labels is not None:
                        header_cols += [str(x) for x in factor_labels.keys()]

                    writer.writerow(header_cols)
                    writer.writerows(
                        model_to_fields(
                            x,
                            factor_labels=factor_labels
                        )
                        for x in objects
                    )

                    response = StreamingResponse(iter([fp.getvalue()]), media_type="text/csv")
                    response.headers["Content-Disposition"] = f"attachment; filename=COE_{slugify(measure or simple_model_name)}_{type}.csv"

                    return response
            
        # finally, execute the generate_routes() method closed over the
        # 'type', 'model', and 'simple_model_name' vars
        generate_routes()
