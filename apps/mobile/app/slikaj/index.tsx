import { useRouter } from 'expo-router';

import { SubjectList } from '@/ui/subject-list';

export default function PickSubjectForCaptureScreen() {
  const router = useRouter();

  return (
    <SubjectList
      onSelect={(subject) =>
        router.push({
          pathname: '/slikaj/[subject]',
          params: { subject: subject.value },
        })
      }
    />
  );
}
