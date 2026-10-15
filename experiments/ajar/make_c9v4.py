"""config_m1_c9v4 = config_m1_c9v3 + description grants (MODEL.md §9.15): the per-suite trusted
structured sources and the entities' targets, exactly the table of §9.15.

    python make_c9v4.py
"""
import os
import shutil

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
EMAILS = ["send_email.recipients", "send_email.cc", "send_email.bcc", "create_calendar_event.participants",
          "add_calendar_event_participants.participants", "share_file.email"]
SOURCES = {
    "banking": {},
    "slack": {
        "get_channels": [{"entity": "channel", "shape": "names", "complete": True}],
        "read_channel_messages": [{"entity": "channel", "shape": "count", "key": "channel", "field": "messages"}],
        "get_users_in_channel": [{"entity": "channel", "shape": "count", "key": "channel", "field": "users"},
                                 {"entity": "channel", "shape": "members", "key": "channel"}],
    },
    "workspace": {
        "search_contacts_by_name": [{"entity": "contact", "shape": "records", "name": "name", "value": "email"}],
        "search_contacts_by_email": [{"entity": "contact", "shape": "records", "name": "name", "value": "email"}],
        "search_calendar_events": [{"entity": "event", "shape": "records", "name": "title", "value": "id_",
                                    "members": "participants"}],
        "get_day_calendar_events": [{"entity": "event", "shape": "records", "name": "title", "value": "id_",
                                     "members": "participants"}],
        "list_files": [{"entity": "file", "shape": "records", "name": "filename", "value": "id_",
                        "fields": ["size"], "complete": True}],
        "search_files": [{"entity": "file", "shape": "records", "name": "filename", "value": "id_",
                          "fields": ["size"]}],
        "search_files_by_filename": [{"entity": "file", "shape": "records", "name": "filename", "value": "id_",
                                      "fields": ["size"]}],
    },
    "travel": {
        "get_all_hotels_in_city": [{"entity": "hotel", "shape": "names", "complete": True}],
        "get_rating_reviews_for_hotels": [{"entity": "hotel", "shape": "keyed", "key": "hotel_names",
                                           "field": "rating", "pattern": "rating"}],
        "get_hotels_prices": [{"entity": "hotel", "shape": "keyed", "key": "hotel_names", "field": "price",
                               "pattern": "price_range"}],
        "get_all_restaurants_in_city": [{"entity": "restaurant", "shape": "names", "complete": True}],
        "get_rating_reviews_for_restaurants": [{"entity": "restaurant", "shape": "keyed", "key": "restaurant_names",
                                                "field": "rating", "pattern": "rating"}],
        "get_price_for_restaurants": [{"entity": "restaurant", "shape": "keyed", "key": "restaurant_names",
                                       "field": "price"}],
        "get_all_car_rental_companies_in_city": [{"entity": "car_rental", "shape": "names", "complete": True}],
        "get_rating_reviews_for_car_rental": [{"entity": "car_rental", "shape": "keyed", "key": "company_name",
                                               "field": "rating", "pattern": "rating"}],
        "get_car_price_per_day": [{"entity": "car_rental", "shape": "keyed", "key": "company_name",
                                   "field": "price"}],
    },
}
TARGETS = {
    "banking": {},
    "slack": {"channel": {"value": ["add_user_to_channel.channel", "send_channel_message.channel"],
                          "members": ["add_user_to_channel.user", "send_direct_message.recipient"]}},
    "workspace": {"contact": {"value": EMAILS},
                  "event": {"value": ["reschedule_calendar_event.event_id", "cancel_calendar_event.event_id",
                                      "add_calendar_event_participants.event_id"], "members": EMAILS},
                  "file": {"value": ["delete_file.file_id", "share_file.file_id", "append_to_file.file_id"]}},
    "travel": {"hotel": {"value": ["reserve_hotel.hotel"]},
               "restaurant": {"value": ["reserve_restaurant.restaurant"]},
               "car_rental": {"value": ["reserve_car_rental.company"]}},
}


def main():
    src, dst = os.path.join(HERE, "config_m1_c9v3"), os.path.join(HERE, "config_m1_c9v4")
    shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(src, dst)
    for s in SOURCES:
        p = os.path.join(dst, f"{s}.yaml")
        cfg = yaml.safe_load(open(p))
        cfg["description_sources"] = SOURCES[s]
        cfg["description_targets"] = TARGETS[s]
        yaml.safe_dump(cfg, open(p, "w"), sort_keys=False)


if __name__ == "__main__":
    main()
