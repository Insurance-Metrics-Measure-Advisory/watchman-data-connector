from watchmen.factors.model.factor import Factor
from watchmen.factors.model.topic import Topic
from watchmen.knowledge.knowledge_loader import find_template_by_domain
from watchmen.storage.topic_schema_storage import save_topic


def test_convert_template():
    ## read insureance template

    insurance_templates = find_template_by_domain("insurance")

    topic_list = []

    for template in insurance_templates:
        # topic.topic_name = template.keys()
        for key ,value in template.items():
            topic = Topic()
            # for x in template.values():
            topic.topic_name = key
            for factor_name, factor_details in value.items():
                factor = Factor(**factor_details)
                factor.factorName = factor_name
                factor.topicName = key
                # factor.dict()

                # for key,value in factor_details.items():
                #     factor[key]=value


                # print(factor_details)

                topic.factors.append(factor)


            # print(topic.json())

            topic_list.append(topic)
    print(topic_list)

    for topic in topic_list:
        save_topic(topic.dict())



    ## save to storage